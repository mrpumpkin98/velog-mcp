"""서버를 stdio 로 띄워 도구 목록과 읽기 도구를 실제 호출해 보는 스모크 테스트.

인증이 필요 없는 조회 도구만 건드리므로 아무 글도 만들지 않는다.

조회할 계정은 인자 → VELOG_USERNAME → 로그인한 계정 순으로 정한다.

    ./.venv/bin/python scripts/smoke_test.py            # 내 계정
    ./.venv/bin/python scripts/smoke_test.py 계정명      # 특정 계정
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


def _text(result) -> str:
    return "\n".join(
        block.text for block in result.content if getattr(block, "type", None) == "text"
    )


async def main(username: str | None) -> int:
    # 부모 환경을 물려받아야 VELOG_TOKEN_STORE 같은 사용자 설정이 유지된다.
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    if username:
        env["VELOG_USERNAME"] = username

    params = StdioServerParameters(
        command=str(ROOT / ".venv" / "bin" / "python"),
        args=["-m", "velog_mcp"],
        env=env,
        cwd=str(ROOT),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"연결됨: {init.serverInfo.name} v{init.serverInfo.version}\n")

            tools = await session.list_tools()
            print(f"도구 {len(tools.tools)}개")
            for tool in tools.tools:
                required = tool.inputSchema.get("required", [])
                print(f"  - {tool.name:34s} 필수인자: {required or '없음'}")

            print("\n[velog_whoami]")
            print(_text(await session.call_tool("velog_whoami", {})))

            label = f"@{username}" if username else "로그인한 계정"
            print(f"\n[velog_list_posts] {label} 최신 3건")
            result = await session.call_tool("velog_list_posts", {"limit": 3})
            payload = json.loads(_text(result))
            for post in payload["posts"]:
                print(f"  - {post['title']}  ({post.get('url')})")

            slug = payload["posts"][0]["url_slug"] if payload["posts"] else None
            if slug:
                print(f"\n[velog_get_post] {slug}")
                detail = json.loads(_text(await session.call_tool("velog_get_post", {"url_slug": slug})))
                body = detail.get("body") or ""
                print(f"  제목: {detail['title']}")
                print(f"  태그: {detail.get('tags')}")
                print(f"  본문 길이: {len(body)}자")

            print("\n[velog_list_series]")
            series = json.loads(_text(await session.call_tool("velog_list_series", {})))
            print(f"  시리즈 {series['count']}개")
            for item in series["series"][:3]:
                print(f"  - {item['name']} ({item['id']})")

            print("\n[velog_delete_post] confirm 없이 호출 → 막혀야 정상")
            guard = await session.call_tool(
                "velog_delete_post", {"post_id": "00000000-0000-0000-0000-000000000000"}
            )
            print(f"  isError={guard.isError} / {_text(guard)}")

    print("\n스모크 테스트 완료")
    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("VELOG_USERNAME")
    raise SystemExit(asyncio.run(main(target)))
