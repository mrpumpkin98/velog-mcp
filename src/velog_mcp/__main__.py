"""MCP 서버 진입점.

기본은 stdio 다. Cursor 가 프로세스를 직접 띄워주므로 설정이 가장 간단하다.

`--http` 를 주면 HTTP(streamable-http)로 뜨면서 OAuth 인증 서버가 함께 켜진다.
이 모드에서만 Cursor 설정 화면에 Connect 버튼이 생긴다(배경은 oauth.py 주석 참고).
대신 프로세스를 직접 띄워둬야 한다.

    python -m velog_mcp                       # stdio (기본)
    python -m velog_mcp --http                # http, 127.0.0.1:8790
    python -m velog_mcp --http --port 9000    # 포트 지정
"""

from __future__ import annotations

import argparse
import logging
import os

DEFAULT_HOST = "127.0.0.1"
# Cursor 데스크톱이 OAuth 콜백에 8787 을 쓴다고 문서에 적혀 있어 피한다.
DEFAULT_PORT = 8790


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="velog-mcp", description="벨로그 MCP 서버")
    parser.add_argument(
        "--http",
        action="store_true",
        default=_env_flag("VELOG_MCP_HTTP"),
        help="stdio 대신 HTTP 로 띄운다. OAuth Connect 버튼을 쓸 수 있다",
    )
    parser.add_argument("--host", default=os.getenv("VELOG_MCP_HOST") or DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=int(os.getenv("VELOG_MCP_PORT") or DEFAULT_PORT))
    return parser.parse_args(argv)


def _env_flag(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    from .server import mcp

    if not args.http:
        mcp.run(transport="stdio")
        return

    # HTTP 모드에서는 로그가 대화를 가릴 걱정이 없으니 진행 상황을 보여준다.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from .http_app import attach_auth, build_auth, register_login_routes

    # 인증 서버 주소는 Cursor 가 이 서버를 부를 때 쓰는 주소와 같아야 한다.
    # 0.0.0.0 으로 바인딩해도 발급 주체(issuer)는 접속 가능한 주소여야 하므로 loopback 으로 적는다.
    advertised_host = DEFAULT_HOST if args.host in {"0.0.0.0", "::", ""} else args.host
    base_url = f"http://{advertised_host}:{args.port}"

    provider, auth_settings = build_auth(base_url)
    attach_auth(mcp, provider, auth_settings)
    register_login_routes(mcp, provider)

    mcp.settings.host = args.host
    mcp.settings.port = args.port

    # 로그를 파일로 넘길 때 파이썬이 stdout 을 블록 버퍼링해서, 서버가 죽으면
    # 정작 원인이 버퍼에 갇힌 채 사라진다. 그래서 여기서는 즉시 흘려보낸다.
    print(f"velog MCP 서버 (HTTP): {base_url}/mcp", flush=True)
    print("Cursor 설정에 아래를 넣고 Connect 를 누르세요:", flush=True)
    print(f'  {{ "velog": {{ "url": "{base_url}/mcp" }} }}', flush=True)

    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
