"""마크다운 발행 도구를 dry-run 으로 검증한다.

VELOG_DRY_RUN=true 이므로 벨로그에 아무것도 보내지 않는다.
프런트매터 해석, H1 제목 승격, 그리고 velog_post_id 가 있을 때 수정 모드로 바뀌는지 확인한다.

    ./.venv/bin/python scripts/dry_run_markdown.py
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]

SAMPLE_WITH_FRONTMATTER = """\
---
title: 트랜잭션 경계를 다시 그은 이유
tags:
  - postgresql
  - transaction
slug: transaction-boundary
draft: true
---

## 문제

쓰기 두 개가 서로 다른 트랜잭션에 있었다.
"""

SAMPLE_H1_ONLY = """\
# 제목이 본문 H1 에만 있는 문서

첫 문단이다.
"""


def _text(result) -> str:
    return "\n".join(
        block.text for block in result.content if getattr(block, "type", None) == "text"
    )


async def main() -> int:
    params = StdioServerParameters(
        command=str(ROOT / ".venv" / "bin" / "python"),
        args=["-m", "velog_mcp"],
        env={
            "PYTHONPATH": str(ROOT / "src"),
            "VELOG_DRY_RUN": "true",
            "VELOG_ACCESS_TOKEN": "dummy-token-for-dry-run",
        },
        cwd=str(ROOT),
    )

    with tempfile.TemporaryDirectory() as tmp:
        doc_a = Path(tmp) / "with-frontmatter.md"
        doc_a.write_text(SAMPLE_WITH_FRONTMATTER, encoding="utf-8")
        doc_b = Path(tmp) / "h1-only.md"
        doc_b.write_text(SAMPLE_H1_ONLY, encoding="utf-8")

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                print("[1] 프런트매터가 있는 문서")
                out = json.loads(
                    _text(
                        await session.call_tool(
                            "velog_publish_markdown_file", {"file_path": str(doc_a)}
                        )
                    )
                )
                sent = out["would_send"]
                print(f"  mode={out['mode']}")
                print(f"  title={sent['title']!r}")
                print(f"  tags={sent['tags']}  slug={sent['url_slug']!r}")
                print(f"  is_temp(draft)={sent['is_temp']}  is_markdown={sent['is_markdown']}")
                print(f"  body 앞부분={sent['body'][:30]!r}")

                print("\n[2] 제목이 H1 에만 있는 문서 (H1 → 제목 승격, 본문에서 제거)")
                out = json.loads(
                    _text(
                        await session.call_tool(
                            "velog_publish_markdown_file", {"file_path": str(doc_b)}
                        )
                    )
                )
                sent = out["would_send"]
                print(f"  title={sent['title']!r}")
                print(f"  body={sent['body']!r}")
                assert not sent["body"].lstrip().startswith("#"), "H1 이 본문에 남아 있다"

                print("\n[3] velog_post_id 가 기록된 문서 → 수정 모드여야 함")
                doc_a.write_text(
                    SAMPLE_WITH_FRONTMATTER.replace(
                        "draft: true",
                        "draft: true\nvelog_post_id: 11111111-2222-3333-4444-555555555555",
                    ),
                    encoding="utf-8",
                )
                out = json.loads(
                    _text(
                        await session.call_tool(
                            "velog_publish_markdown_file", {"file_path": str(doc_a)}
                        )
                    )
                )
                print(f"  mode={out['mode']}  id={out['would_send'].get('id')}")
                assert out["mode"] == "update", "수정 모드로 바뀌지 않았다"

                print("\n[4] 상대 경로는 거부되어야 함")
                bad = await session.call_tool(
                    "velog_publish_markdown_file", {"file_path": "relative/path.md"}
                )
                print(f"  isError={bad.isError} / {_text(bad)}")
                assert bad.isError

                print("\n[5] draft 인자로 프런트매터 덮어쓰기")
                out = json.loads(
                    _text(
                        await session.call_tool(
                            "velog_publish_markdown_file",
                            {"file_path": str(doc_a), "draft": False},
                        )
                    )
                )
                print(f"  is_temp={out['would_send']['is_temp']} (프런트매터는 true 였음)")
                assert out["would_send"]["is_temp"] is False

    print("\n모든 검증 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
