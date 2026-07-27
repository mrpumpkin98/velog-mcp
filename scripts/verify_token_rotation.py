"""토큰 자동 갱신(Set-Cookie 흡수)이 실제로 동작하는지 검증한다.

벨로그 실서버로는 유효한 토큰이 있어야 확인할 수 있으므로, 벨로그처럼 응답하는
로컬 가짜 서버를 띄워 검증한다. 확인 항목:

  1. 요청에 Cookie 로 토큰이 실려 나가는가
  2. 응답의 Set-Cookie 에 담긴 새 토큰을 흡수하는가
  3. 흡수한 토큰이 저장소 파일에 기록되는가
  4. 다음 요청에 갱신된 토큰이 실려 나가는가
  5. VELOG_PERSIST_TOKENS=false 면 파일에 쓰지 않는가

    ./.venv/bin/python scripts/verify_token_rotation.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

ROTATED_ACCESS = "rotated-access-token-value"
ROTATED_REFRESH = "rotated-refresh-token-value"

received_cookies: list[str] = []


class FakeVelogHandler(BaseHTTPRequestHandler):
    """첫 요청에만 새 토큰을 Set-Cookie 로 내려주는 가짜 벨로그."""

    rotate_next = True

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        received_cookies.append(self.headers.get("Cookie", ""))

        self.send_response(200)
        self.send_header("Content-Type", "application/json")

        if FakeVelogHandler.rotate_next:
            FakeVelogHandler.rotate_next = False
            # 벨로그가 만료된 access_token 을 갱신해줄 때의 형태를 모사한다.
            self.send_header(
                "Set-Cookie",
                f"access_token={ROTATED_ACCESS}; Domain=.velog.io; Path=/; HttpOnly; SameSite=Lax",
            )
            self.send_header(
                "Set-Cookie",
                f"refresh_token={ROTATED_REFRESH}; Domain=.velog.io; Path=/; HttpOnly; SameSite=Lax",
            )

        body = json.dumps(
            {"data": {"auth": {"id": "u1", "username": "tester", "email": "t@example.com",
                               "profile": {"display_name": "테스터", "thumbnail": None}}}}
        ).encode()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # 테스트 출력 오염 방지
        pass


def _cookie_value(header: str, name: str) -> str | None:
    for part in header.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return None


async def run_checks(endpoint: str, store: Path) -> None:
    # 설정 로드 시점에 환경변수를 읽으므로 import 전에 세팅한다.
    os.environ["VELOG_TOKEN_STORE"] = str(store)
    os.environ["VELOG_GRAPHQL_ENDPOINT"] = endpoint
    os.environ["VELOG_ACCESS_TOKEN"] = "seed-access-token"
    os.environ["VELOG_REFRESH_TOKEN"] = "seed-refresh-token"
    os.environ["VELOG_PERSIST_TOKENS"] = "true"

    from velog_mcp.client import VelogClient
    from velog_mcp.config import load_settings
    from velog_mcp.token_store import load_tokens

    settings = load_settings()
    print(f"[준비] 토큰 출처={settings.token_source} (저장소가 비어 있어 환경변수 씨앗값 사용)")
    assert settings.token_source == "env", settings.token_source
    assert settings.access_token == "seed-access-token"

    client = VelogClient(settings)
    try:
        print("\n[1] 첫 요청 — 씨앗 토큰이 Cookie 로 나가고, 응답의 새 토큰을 흡수해야 함")
        auth = await client.whoami()
        assert auth and auth["username"] == "tester", auth
        sent = received_cookies[0]
        print(f"  보낸 access_token = {_cookie_value(sent, 'access_token')}")
        assert _cookie_value(sent, "access_token") == "seed-access-token"
        assert _cookie_value(sent, "refresh_token") == "seed-refresh-token"

        print(f"  흡수한 access_token = {client.settings.access_token}")
        assert client.settings.access_token == ROTATED_ACCESS
        assert client.settings.refresh_token == ROTATED_REFRESH

        print("\n[2] 저장소 파일에 기록되었는지")
        stored = load_tokens(store)
        print(f"  파일 access_token = {stored.access_token}")
        print(f"  파일 갱신 시각    = {stored.updated_at}")
        assert stored.access_token == ROTATED_ACCESS
        assert stored.refresh_token == ROTATED_REFRESH
        mode = oct(store.stat().st_mode & 0o777)
        print(f"  파일 권한        = {mode}")
        assert mode == "0o600", mode

        print("\n[3] 두 번째 요청 — 갱신된 토큰이 실려 나가야 함")
        await client.whoami()
        sent = received_cookies[1]
        print(f"  보낸 access_token = {_cookie_value(sent, 'access_token')}")
        assert _cookie_value(sent, "access_token") == ROTATED_ACCESS
    finally:
        await client.aclose()

    print("\n[4] 저장소가 채워졌으면 환경변수보다 저장소가 우선해야 함")
    reloaded = load_settings()
    print(f"  토큰 출처={reloaded.token_source}, access={reloaded.access_token}")
    assert reloaded.token_source == "store"
    assert reloaded.access_token == ROTATED_ACCESS

    print("\n[5] VELOG_PERSIST_TOKENS=false 면 파일을 건드리지 않아야 함")
    os.environ["VELOG_PERSIST_TOKENS"] = "false"
    FakeVelogHandler.rotate_next = True
    store.write_text(json.dumps({"access_token": "untouched", "refresh_token": "untouched"}))
    no_persist = load_settings()
    client2 = VelogClient(no_persist)
    try:
        await client2.whoami()
        assert client2.settings.access_token == ROTATED_ACCESS  # 메모리는 갱신
        after = load_tokens(store)
        print(f"  메모리={client2.settings.access_token} / 파일={after.access_token}")
        assert after.access_token == "untouched", "파일이 덮어써졌다"
    finally:
        await client2.aclose()


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeVelogHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp) / "tokens.json"
        try:
            asyncio.run(run_checks(f"http://127.0.0.1:{port}/graphql", store))
        finally:
            server.shutdown()

    print("\n모든 검증 통과 — 토큰 자동 갱신이 동작합니다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
