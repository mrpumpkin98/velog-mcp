"""stdio 트랜스포트로 MCP 서버를 띄운다."""

from __future__ import annotations

from .server import mcp


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
