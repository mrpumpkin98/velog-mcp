"""설치 상태를 점검하고 다음에 할 일을 알려준다.

처음 설치했을 때, 또는 뭔가 동작하지 않을 때 가장 먼저 실행한다.
아무것도 바꾸지 않고 확인만 한다.

    ./.venv/bin/python scripts/doctor.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

ROOT = Path(__file__).resolve().parents[1]
CURSOR_CONFIG = Path.home() / ".cursor" / "mcp.json"
REG_LABEL = "클라이언트 등록"

OK = "✓"
NO = "✗"
WARN = "!"

results: list[tuple[str, str, str]] = []
next_steps: list[str] = []


def check(status: str, label: str, detail: str = "") -> None:
    results.append((status, label, detail))


def check_python() -> None:
    version = sys.version_info
    label = f"Python {version.major}.{version.minor}.{version.micro}"
    if version >= (3, 11):
        check(OK, label)
    else:
        check(NO, label, "3.11 이상이 필요합니다")
        next_steps.append("Python 3.11 이상으로 venv 를 다시 만드세요")


def check_venv() -> Path | None:
    interpreter = Path(sys.executable)
    expected = ROOT / ".venv" / "bin" / "python"
    if expected.exists():
        check(OK, "가상환경(.venv)", str(expected))
        return expected
    check(WARN, "가상환경(.venv)", f"없음 — 지금 실행 중인 인터프리터: {interpreter}")
    next_steps.append(f"cd {ROOT} && python3 -m venv .venv")
    return None


REQUIRED = (
    ("mcp", "mcp[cli]"),
    ("httpx", "httpx"),
    ("frontmatter", "python-frontmatter"),
)


def check_dependencies() -> bool:
    missing = []
    for module, package in REQUIRED:
        try:
            __import__(module)
        except ImportError:
            missing.append(package)

    if missing:
        check(NO, "필수 패키지", f"누락: {', '.join(missing)}")
        next_steps.append(f'{sys.executable} -m pip install -e "{ROOT}"')
        return False
    check(OK, "필수 패키지", ", ".join(package for _, package in REQUIRED))
    return True


def check_playwright() -> None:
    try:
        import playwright  # noqa: F401
    except ImportError:
        check(WARN, "playwright", "없음 — 브라우저 로그인(velog_login)을 쓸 수 없습니다")
        next_steps.append(f'{sys.executable} -m pip install -e "{ROOT}[login]"')
        next_steps.append(f"{sys.executable} -m playwright install chromium")
        return

    # 브라우저 실행 파일까지 설치됐는지 확인한다. 패키지만 있고 브라우저가 없는 경우가 흔하다.
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            path = Path(pw.chromium.executable_path)
        if path.exists():
            check(OK, "playwright + Chromium")
        else:
            raise FileNotFoundError(path)
    except Exception:
        check(WARN, "Chromium", "설치되지 않음")
        next_steps.append(f"{sys.executable} -m playwright install chromium")


def check_server_import() -> None:
    try:
        from velog_mcp import mcp

        count = len(mcp._tool_manager.list_tools())
        check(OK, "서버 로드", f"도구 {count}개")
    except Exception as exc:
        check(NO, "서버 로드", f"{type(exc).__name__}: {exc}")
        next_steps.append("서버 import 실패 — 위의 패키지 설치를 먼저 해결하세요")


def check_tokens() -> None:
    try:
        from velog_mcp.token_store import load_tokens, store_path
    except ImportError:
        return

    tokens = load_tokens()
    if tokens.is_empty:
        check(WARN, "벨로그 로그인", f"저장된 토큰 없음 ({store_path()})")
        next_steps.append(
            '에이전트에게 "벨로그 로그인해줘" 라고 말하거나 '
            f"`{sys.executable} scripts/login.py` 실행"
        )
    else:
        detail = f"갱신 {tokens.updated_at}"
        if not tokens.refresh_token:
            detail += " (refresh_token 없음 — 만료가 빨라집니다)"
        check(OK, "벨로그 로그인", detail)


def _is_inside_project(path: Path) -> bool:
    try:
        path.relative_to(ROOT)
    except ValueError:
        return False
    return True


def check_client_registration() -> None:
    """Cursor 설정을 기준으로 등록 여부를 본다.

    다른 MCP 클라이언트(Claude Desktop 등)를 쓸 수도 있으므로, 못 찾았을 때는
    실패가 아니라 주의로 처리하고 넣을 설정을 알려준다.
    """
    if not CURSOR_CONFIG.exists():
        check(WARN, REG_LABEL, f"Cursor 설정 없음 ({CURSOR_CONFIG})")
        next_steps.append("쓰는 MCP 클라이언트의 설정 파일에 아래 설정을 넣으세요 (하단 참고)")
        next_steps.append("클라이언트를 완전히 종료한 뒤 다시 켜세요 (시작할 때만 서버를 읽습니다)")
        return

    try:
        config = json.loads(CURSOR_CONFIG.read_text(encoding="utf-8"))
    except ValueError as exc:
        check(NO, REG_LABEL, f"{CURSOR_CONFIG.name} 파싱 실패: {exc}")
        next_steps.append(f"{CURSOR_CONFIG} 의 JSON 문법을 고치세요")
        return

    servers = config.get("mcpServers") or {}
    entry = servers.get("velog")
    if not entry:
        check(WARN, REG_LABEL, f"Cursor 에 velog 항목 없음 (등록된 서버: {sorted(servers) or '없음'})")
        next_steps.append("클라이언트 설정의 mcpServers 에 velog 항목을 추가하세요 (하단 참고)")
        next_steps.append("클라이언트를 완전히 종료한 뒤 다시 켜세요 (시작할 때만 서버를 읽습니다)")
        return

    # HTTP 모드로 등록한 경우. 이때는 Cursor 가 서버를 띄워주지 않으므로
    # 경로가 아니라 '켜져 있는지'가 관심사다.
    if entry.get("url") and not entry.get("command"):
        url = entry["url"]
        if _http_server_alive(url):
            check(OK, REG_LABEL, f"HTTP 모드, 응답 있음 ({url})")
        else:
            check(WARN, REG_LABEL, f"HTTP 모드인데 응답이 없음 ({url})")
            next_steps.append(
                "HTTP 모드는 서버를 직접 켜둬야 합니다: python -m velog_mcp --http"
            )
        return

    command = entry.get("command", "")
    if not Path(command).exists():
        check(NO, REG_LABEL, f"command 경로가 존재하지 않음: {command}")
        next_steps.append("설정의 command 를 실제 python 경로로 고치세요 (하단 참고)")
        return

    # 다른 위치의 클론을 가리키고 있으면, 지금 고친 코드가 반영되지 않는다.
    # .venv/bin/python 은 시스템 파이썬을 가리키는 심볼릭 링크이므로 resolve() 하면 안 된다.
    if not _is_inside_project(Path(command).expanduser()):
        check(WARN, REG_LABEL, f"다른 위치를 가리킴: {command}")
        next_steps.append(
            f"설정의 command 를 이 프로젝트로 바꾸세요: {ROOT / '.venv' / 'bin' / 'python'}"
        )
        return

    check(OK, REG_LABEL, command)


def _http_server_alive(url: str) -> bool:
    """HTTP 모드 서버가 떠 있는지 본다.

    인증이 걸려 있어 200 이 아니라 401 이 정상이다. '응답이 온다'는 것만 확인한다.
    """
    from urllib.error import HTTPError, URLError
    from urllib.parse import urlparse
    from urllib.request import urlopen

    parsed = urlparse(url)
    probe = f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-authorization-server"
    try:
        with urlopen(probe, timeout=3) as response:
            return response.status < 500
    except HTTPError:
        return True  # 응답은 온 것이니 서버는 살아 있다
    except (URLError, OSError):
        return False


def print_snippet() -> None:
    interpreter = ROOT / ".venv" / "bin" / "python"
    snippet = {
        "mcpServers": {
            "velog": {"command": str(interpreter), "args": ["-m", "velog_mcp"]}
        }
    }
    print("\n" + "─" * 62)
    print("MCP 클라이언트 설정에 넣을 내용:")
    print("─" * 62)
    print(json.dumps(snippet, indent=2, ensure_ascii=False))
    print(f"\n  Cursor          : {CURSOR_CONFIG}")
    print("  Claude Desktop  : ~/Library/Application Support/Claude/claude_desktop_config.json")
    print("\n(이미 다른 서버가 있다면 mcpServers 안에 velog 항목만 추가하세요)")
    print(
        "\n설정 화면의 Connect 버튼으로 로그인하려면 HTTP 모드를 쓰세요.\n"
        "  python -m velog_mcp --http\n"
        '  설정에는 command 대신: { "velog": { "url": "http://127.0.0.1:8790/mcp" } }\n'
        "  (대신 서버를 직접 켜둬야 합니다. 자세한 내용은 README)"
    )


def main() -> int:
    print("velog-mcp 설치 점검\n" + "=" * 62)

    # 점검 순서 = 처음 설치할 때의 진행 순서. 다음 할 일 목록이 그 순서로 쌓인다.
    # 로그인은 등록 뒤에 둔다 — 에이전트로 로그인하려면 서버가 먼저 붙어 있어야 한다.
    check_python()
    check_venv()
    deps_ok = check_dependencies()
    check_playwright()
    if deps_ok:
        check_server_import()
    check_client_registration()
    if deps_ok:
        check_tokens()

    width = max(len(label) for _, label, _ in results)
    for status, label, detail in results:
        line = f"  {status} {label.ljust(width)}"
        if detail:
            line += f"   {detail}"
        print(line)

    failures = sum(1 for status, _, _ in results if status == NO)
    warnings = sum(1 for status, _, _ in results if status == WARN)

    print("\n" + "=" * 62)
    if not failures and not warnings:
        print("모두 준비되었습니다. 클라이언트를 재시작하면 도구가 잡힙니다.")
        print('사용 예: "이 문서 벨로그에 임시저장으로 올려줘"')
        return 0

    print(f"문제 {failures}건, 주의 {warnings}건\n")
    print("다음 순서로 진행하세요:")
    for index, step in enumerate(dict.fromkeys(next_steps), start=1):
        print(f"  {index}. {step}")

    if any(status != OK for status, label, _ in results if label == REG_LABEL):
        print_snippet()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
