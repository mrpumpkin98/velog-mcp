"""브라우저로 벨로그에 로그인해 토큰을 추출한다.

벨로그에는 비밀번호 로그인이 없다(이메일 매직링크 또는 소셜 OAuth만 지원). 그래서
자격증명을 받아 자동 로그인하는 방법이 없고, 브라우저를 띄워 사람이 한 번 인증하게 한 뒤
쿠키에서 토큰을 꺼내오는 방식을 쓴다.

브라우저 프로필을 재사용하므로 두 번째부터는 이미 로그인된 상태로 열려서, 창을 띄우지 않고
(headless) 토큰만 갱신할 수 있다.

MCP 도구(server.velog_login)와 CLI(scripts/login.py)가 이 모듈을 공유한다.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

LOGIN_URL = "https://velog.io/?to=%2F"
TOKEN_COOKIES = ("access_token", "refresh_token")
POLL_INTERVAL_SEC = 1.5


class BrowserLoginError(RuntimeError):
    """브라우저 로그인 실패."""


class PlaywrightMissingError(BrowserLoginError):
    """playwright 패키지 또는 Chromium 이 없음."""


def profile_dir() -> Path:
    override = (os.getenv("VELOG_BROWSER_PROFILE") or "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".velog-mcp" / "browser"


async def extract_tokens(
    *,
    headless: bool = False,
    timeout_sec: int = 180,
    on_progress=None,
) -> dict[str, str]:
    """브라우저를 띄워 토큰을 추출한다.

    on_progress: 진행 상황을 알릴 콜백(문자열 하나를 받는다). CLI 는 print, MCP 는 로거를 넘긴다.
    반환: {"access_token": ..., "refresh_token": ...}
    실패 시 BrowserLoginError 계열 예외.
    """
    notify = on_progress or (lambda _message: None)

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise PlaywrightMissingError(
            "playwright 가 설치되지 않았습니다. 다음을 실행하세요:\n"
            "  pip install 'velog-mcp[login]'\n"
            "  python -m playwright install chromium"
        ) from exc

    profile = profile_dir()
    profile.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        try:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=headless,
                viewport={"width": 1280, "height": 900},
            )
        except Exception as exc:
            raise PlaywrightMissingError(
                f"Chromium 을 실행할 수 없습니다: {exc}\n"
                "브라우저가 없다면: python -m playwright install chromium"
            ) from exc

        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(LOGIN_URL, wait_until="domcontentloaded")

            if not headless:
                notify(
                    "브라우저 창에서 벨로그에 로그인하세요 "
                    "(이메일 링크 또는 GitHub·Google — 비밀번호 방식은 벨로그에 없습니다)"
                )

            tokens = await _poll_for_tokens(
                context, timeout_sec=timeout_sec, notify=notify, headless=headless
            )
        finally:
            await context.close()

    if not tokens:
        if headless:
            raise BrowserLoginError(
                "저장된 브라우저 프로필에 로그인 정보가 없습니다. "
                "headless 를 끄고 다시 시도해 브라우저에서 직접 로그인하세요"
            )
        raise BrowserLoginError(
            f"{timeout_sec}초 안에 로그인이 완료되지 않았습니다. 다시 시도하세요"
        )

    return tokens


async def _poll_for_tokens(
    context, *, timeout_sec: int, notify, headless: bool
) -> dict[str, str] | None:
    """쿠키에 access_token 이 나타날 때까지 주기적으로 확인한다.

    이미 로그인된 프로필이면 첫 확인에서 바로 찾는다.
    """
    waited = 0.0
    announced = False
    while waited <= timeout_sec:
        tokens = {
            cookie["name"]: cookie["value"]
            for cookie in await context.cookies()
            if cookie["name"] in TOKEN_COOKIES and cookie.get("value")
        }
        if tokens.get("access_token"):
            return tokens

        if not headless and not announced and waited >= POLL_INTERVAL_SEC * 3:
            notify("로그인 대기 중…")
            announced = True

        await asyncio.sleep(POLL_INTERVAL_SEC)
        waited += POLL_INTERVAL_SEC

    return None
