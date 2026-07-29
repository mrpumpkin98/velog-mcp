#!/usr/bin/env python3
"""HTTP 모드 서버를 macOS 로그인 시 자동으로 띄운다.

HTTP 모드는 Cursor 가 프로세스를 대신 띄워주지 않아서, 꺼져 있으면 도구가 사라진다.
그 불편을 없애려고 launchd 에 등록한다. KeepAlive 를 켜두므로 서버가 죽어도 다시 뜬다.

    python scripts/install_launch_agent.py            # 등록하고 바로 시작
    python scripts/install_launch_agent.py --status    # 지금 상태만 보기
    python scripts/install_launch_agent.py --uninstall # 등록 해제

stdio 모드를 쓰는 사람은 이 스크립트가 필요 없다.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABEL = "com.github.velog-mcp.http"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG_PATH = Path.home() / ".velog-mcp" / "http.log"
DEFAULT_PORT = 8790


def _interpreter() -> Path:
    return ROOT / ".venv" / "bin" / "python"


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True)


def _is_loaded() -> bool:
    return _run(["launchctl", "print", f"{_domain()}/{LABEL}"]).returncode == 0


def _wait_until(loaded: bool, timeout: float = 10.0) -> bool:
    """launchctl 은 요청을 받고 바로 끝내므로 결과를 기다려야 한다.

    bootout 이 끝나기 전에 bootstrap 을 치면 서로 엇갈려서, 명령은 성공했는데
    정작 서비스가 없는 상태가 된다(실측). 그래서 상태를 확인하고 넘어간다.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _is_loaded() == loaded:
            return True
        time.sleep(0.3)
    return _is_loaded() == loaded


def build_plist(port: int) -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [str(_interpreter()), "-m", "velog_mcp", "--http", "--port", str(port)],
        "WorkingDirectory": str(ROOT),
        "EnvironmentVariables": {
            # 로그가 버퍼에 갇혀 사라지지 않게 한다. 죽은 이유를 봐야 한다.
            "PYTHONUNBUFFERED": "1",
            "HOME": str(Path.home()),
        },
        "RunAtLoad": True,
        # 서버가 죽어도 다시 띄운다. HTTP 모드의 가장 큰 약점을 여기서 막는다.
        "KeepAlive": True,
        "StandardOutPath": str(LOG_PATH),
        "StandardErrorPath": str(LOG_PATH),
        # ~/Library/LaunchAgents 는 로그인 세션에서 돌기 때문에,
        # 벨로그 로그인 창(Chromium)을 띄울 수 있다.
        "ProcessType": "Interactive",
    }


def status() -> int:
    print(f"레이블   : {LABEL}")
    print(f"plist    : {PLIST_PATH}  {'(있음)' if PLIST_PATH.exists() else '(없음)'}")
    print(f"로그      : {LOG_PATH}")

    result = _run(["launchctl", "print", f"{_domain()}/{LABEL}"])
    if result.returncode != 0:
        print("상태      : 등록되지 않음")
        return 1

    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith(("state =", "pid =", "last exit code =")):
            print(f"상태      : {stripped}")
    return 0


def install(port: int) -> int:
    interpreter = _interpreter()
    if not interpreter.exists():
        print(f"가상환경 파이썬이 없습니다: {interpreter}", file=sys.stderr)
        print("먼저 설치를 마치세요: python scripts/doctor.py", file=sys.stderr)
        return 1

    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    # 이미 등록돼 있으면 먼저 내린다. 안 그러면 bootstrap 이 거절한다.
    if _is_loaded():
        _run(["launchctl", "bootout", f"{_domain()}/{LABEL}"])
        if not _wait_until(loaded=False):
            print("기존 서비스를 내리지 못했습니다. 잠시 뒤 다시 실행해보세요.", file=sys.stderr)
            return 1

    with PLIST_PATH.open("wb") as handle:
        plistlib.dump(build_plist(port), handle)
    print(f"plist 를 만들었습니다: {PLIST_PATH}")

    result = _run(["launchctl", "bootstrap", _domain(), str(PLIST_PATH)])
    if result.returncode != 0:
        # 구버전 macOS 호환
        result = _run(["launchctl", "load", "-w", str(PLIST_PATH)])

    if not _wait_until(loaded=True):
        detail = result.stderr.strip() or result.stdout.strip() or "이유를 알 수 없습니다"
        print(f"등록 실패: {detail}", file=sys.stderr)
        return 1

    print(f"등록했습니다. 로그인할 때마다 자동으로 뜹니다 (포트 {port}).")
    print()
    print("Cursor 설정에 넣을 내용:")
    print(f'  {{ "mcpServers": {{ "velog": {{ "url": "http://127.0.0.1:{port}/mcp" }} }} }}')
    print()
    print(f"로그: {LOG_PATH}")
    print("확인: python scripts/install_launch_agent.py --status")
    return 0


def uninstall() -> int:
    result = _run(["launchctl", "bootout", f"{_domain()}/{LABEL}"])
    if result.returncode != 0:
        _run(["launchctl", "unload", "-w", str(PLIST_PATH)])
    _wait_until(loaded=False)

    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
        print(f"plist 를 지웠습니다: {PLIST_PATH}")
    else:
        print("등록된 plist 가 없습니다")

    print("자동 시작을 해제했습니다. stdio 모드를 쓰려면 Cursor 설정을 command 방식으로 돌리세요.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="velog-mcp HTTP 모드 자동 시작 등록 (macOS)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--status", action="store_true", help="상태만 확인한다")
    parser.add_argument("--uninstall", action="store_true", help="자동 시작을 해제한다")
    args = parser.parse_args()

    if sys.platform != "darwin":
        print("이 스크립트는 macOS(launchd) 전용입니다.", file=sys.stderr)
        print("리눅스라면 systemd --user 로 같은 일을 할 수 있습니다.", file=sys.stderr)
        return 1

    if args.status:
        return status()
    if args.uninstall:
        return uninstall()
    return install(args.port)


if __name__ == "__main__":
    sys.exit(main())
