"""벨로그 로그인 토큰을 추출해 저장한다 (CLI).

같은 일을 MCP 도구 `velog_login` 으로도 할 수 있다. 에이전트에게 "벨로그 로그인해줘"라고
말하면 되므로, 이 스크립트는 MCP 없이 확인하거나 상태만 보고 싶을 때 쓴다.

    ./.venv/bin/python scripts/login.py              # 창을 띄워 로그인
    ./.venv/bin/python scripts/login.py --headless   # 저장된 프로필로 조용히 갱신
    ./.venv/bin/python scripts/login.py --status     # 지금 저장된 토큰만 확인
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from velog_mcp.browser_login import (  # noqa: E402
    BrowserLoginError,
    extract_tokens,
    profile_dir,
)
from velog_mcp.token_store import load_tokens, save_tokens, store_path  # noqa: E402


def _mask(token: str | None) -> str:
    if not token:
        return "(없음)"
    return f"{token[:12]}…{token[-6:]} ({len(token)}자)"


def show_status() -> int:
    tokens = load_tokens()
    print(f"토큰 저장 위치   : {store_path()}")
    print(f"브라우저 프로필  : {profile_dir()}")
    if tokens.is_empty:
        print("\n저장된 토큰이 없습니다. 옵션 없이 실행해 로그인하세요.")
        return 1
    print(f"갱신 시각        : {tokens.updated_at or '(알 수 없음)'}")
    print(f"access           : {_mask(tokens.access_token)}")
    print(f"refresh          : {_mask(tokens.refresh_token)}")
    return 0


async def run_login(*, headless: bool, timeout_sec: int) -> int:
    try:
        tokens = await extract_tokens(
            headless=headless, timeout_sec=timeout_sec, on_progress=print
        )
    except BrowserLoginError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1

    path = save_tokens(
        access_token=tokens.get("access_token"),
        refresh_token=tokens.get("refresh_token"),
    )
    print("\n토큰을 저장했습니다.")
    print(f"  위치    : {path}")
    print(f"  access  : {_mask(tokens.get('access_token'))}")
    print(f"  refresh : {_mask(tokens.get('refresh_token'))}")
    print("\nMCP 서버가 이 토큰을 자동으로 사용합니다(환경변수보다 우선).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="벨로그 로그인 토큰을 추출해 저장한다")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="창 없이 실행. 이미 로그인된 프로필이 있을 때 토큰 갱신용",
    )
    parser.add_argument("--status", action="store_true", help="저장된 토큰만 확인하고 종료")
    parser.add_argument(
        "--timeout", type=int, default=180, help="로그인 대기 시간(초). 기본 180"
    )
    args = parser.parse_args()

    if args.status:
        return show_status()
    return asyncio.run(run_login(headless=args.headless, timeout_sec=args.timeout))


if __name__ == "__main__":
    raise SystemExit(main())
