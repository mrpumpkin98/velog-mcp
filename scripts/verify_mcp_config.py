"""~/.cursor/mcp.json 에 등록된 설정 그대로 서버를 띄워 연결을 검증한다.

mcp.json 의 command·args·env 를 읽어 그대로 실행하므로, Cursor 가 붙일 때와 같은 조건에서
확인할 수 있다. 조회 도구만 호출하며 글을 만들지 않는다.

    ./.venv/bin/python scripts/verify_mcp_config.py [서버이름]
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CONFIG_PATH = Path.home() / ".cursor" / "mcp.json"


def _text(result) -> str:
    return "\n".join(
        block.text for block in result.content if getattr(block, "type", None) == "text"
    )


def load_server_config(name: str) -> dict:
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"{CONFIG_PATH} 를 읽을 수 없습니다: {exc}")

    servers = config.get("mcpServers") or {}
    if name not in servers:
        raise SystemExit(
            f"'{name}' 서버가 등록되어 있지 않습니다. 등록된 서버: {sorted(servers) or '없음'}"
        )
    return servers[name]


async def main(name: str) -> int:
    entry = load_server_config(name)
    print(f"설정 파일 : {CONFIG_PATH}")
    print(f"command  : {entry.get('command')}")
    print(f"args     : {entry.get('args')}")
    # env 값에 토큰이 있을 수 있으므로 키 이름만 보여준다.
    print(f"env 키   : {sorted((entry.get('env') or {}))or '없음'}\n")

    params = StdioServerParameters(
        command=entry["command"],
        args=entry.get("args") or [],
        env=entry.get("env") or None,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"✓ 연결 성공: {init.serverInfo.name} v{init.serverInfo.version}")

            tools = await session.list_tools()
            print(f"✓ 도구 {len(tools.tools)}개 노출\n")
            for tool in tools.tools:
                print(f"    {tool.name}")

            print("\n[인증 상태]")
            whoami = json.loads(_text(await session.call_tool("velog_whoami", {})))
            # 미인증이면 whoami 가 username 대신 default_username(VELOG_USERNAME)만 준다.
            username = whoami.get("username") or whoami.get("default_username")
            if whoami.get("authenticated"):
                print(f"  ✓ 로그인됨: @{username} ({whoami.get('display_name')})")
                print(f"    토큰 출처: {whoami.get('token_source')}")
            else:
                print(f"  ✗ 미인증: {whoami.get('reason')}")
                print(f"    토큰 저장 위치: {whoami.get('token_store')}")

            # 조회는 인증이 없어도 되지만 대상 계정은 있어야 한다.
            # 남의 계정을 예시로 박아두지 않고, 확인 가능한 계정이 있을 때만 호출한다.
            if username:
                print(f"\n[조회 도구 실동작 — @{username}]")
                posts = json.loads(
                    _text(
                        await session.call_tool(
                            "velog_list_posts", {"username": username, "limit": 2}
                        )
                    )
                )
                for post in posts["posts"]:
                    print(f"  - {post['title']}")
                if not posts["posts"]:
                    print("  (글 없음 — 호출 자체는 성공)")
            else:
                print("\n[조회 도구 실동작] 건너뜀 — 대상 계정을 알 수 없습니다.")
                print("  로그인 후 다시 실행하거나 scripts/smoke_test.py 계정명 을 쓰세요.")

    print("\n연결 검증 완료")
    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "velog"
    raise SystemExit(asyncio.run(main(target)))
