"""벨로그 GraphQL 클라이언트."""

from __future__ import annotations

import logging
from http.cookies import SimpleCookie
from typing import Any

import httpx

from . import graphql as gql
from .config import Settings
from .token_store import save_tokens

logger = logging.getLogger(__name__)

# 벨로그 서버는 브라우저에서 온 요청으로 보이는지를 따지므로 Origin·Referer 를 함께 보낸다.
_BASE_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://velog.io",
    "Referer": "https://velog.io/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
}

_TOKEN_COOKIES = ("access_token", "refresh_token")


class VelogError(RuntimeError):
    """벨로그 API 호출 실패."""


class VelogAuthError(VelogError):
    """인증 실패 또는 권한 없음."""


class VelogClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            headers=dict(_BASE_HEADERS),
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )

    @property
    def settings(self) -> Settings:
        return self._settings

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---------- 내부 ----------

    def _request_headers(self) -> dict[str, str]:
        cookie = self._settings.cookie_header()
        return {"Cookie": cookie} if cookie else {}

    def _absorb_rotated_tokens(self, response: httpx.Response) -> None:
        """응답의 Set-Cookie 에 새 토큰이 있으면 메모리와 저장소를 갱신한다.

        벨로그는 access_token 이 만료됐을 때 refresh_token 을 보고 새 access_token 을
        Set-Cookie 로 내려준다. 이걸 흘려버리면 매번 만료된 토큰으로 재요청하게 되므로
        여기서 붙잡아 둔다. 로그아웃(빈 값) 응답은 무시한다.
        """
        raw_cookies = response.headers.get_list("set-cookie")
        if not raw_cookies:
            return

        rotated: dict[str, str] = {}
        for raw in raw_cookies:
            jar = SimpleCookie()
            try:
                jar.load(raw)
            except Exception:  # 파싱 불가한 쿠키는 조용히 건너뛴다
                continue
            for name in _TOKEN_COOKIES:
                morsel = jar.get(name)
                if morsel is not None and morsel.value:
                    rotated[name] = morsel.value

        if not rotated:
            return

        access = rotated.get("access_token", self._settings.access_token)
        refresh = rotated.get("refresh_token", self._settings.refresh_token)
        if access == self._settings.access_token and refresh == self._settings.refresh_token:
            return

        self._settings = self._settings.with_tokens(
            access_token=access, refresh_token=refresh
        )
        logger.info("벨로그가 새 토큰을 내려주어 갱신했습니다 (%s)", ", ".join(sorted(rotated)))

        if not self._settings.persist_tokens:
            return
        try:
            save_tokens(access_token=access, refresh_token=refresh)
        except OSError as exc:
            # 저장 실패가 요청 자체를 실패시키면 안 된다. 이번 프로세스에서는 메모리 값으로 계속 쓴다.
            logger.warning("토큰을 저장하지 못했습니다: %s", exc)

    async def _execute(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        *,
        operation: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": query}
        if variables:
            # None 은 '변경하지 않음'을 뜻하므로 아예 보내지 않는다.
            payload["variables"] = {k: v for k, v in variables.items() if v is not None}

        try:
            response = await self._client.post(
                self._settings.endpoint, json=payload, headers=self._request_headers()
            )
        except httpx.HTTPError as exc:
            raise VelogError(f"{operation}: 벨로그 서버에 연결하지 못했습니다 ({exc})") from exc

        self._absorb_rotated_tokens(response)

        try:
            body = response.json()
        except ValueError as exc:
            raise VelogError(
                f"{operation}: 응답이 JSON 이 아닙니다 (HTTP {response.status_code})"
            ) from exc

        errors = body.get("errors")
        if errors:
            message = "; ".join(
                str(e.get("message", "알 수 없는 오류")) for e in errors if isinstance(e, dict)
            )
            if _looks_like_auth_error(message):
                raise VelogAuthError(f"{operation}: 인증에 실패했습니다 — {message}")
            raise VelogError(f"{operation}: {message}")

        data = body.get("data")
        if data is None:
            raise VelogError(f"{operation}: 응답에 data 가 없습니다 (HTTP {response.status_code})")
        return data

    # ---------- 조회 ----------

    async def whoami(self) -> dict[str, Any] | None:
        data = await self._execute(gql.AUTH_QUERY, operation="계정 확인")
        return data.get("auth")

    async def list_posts(
        self,
        *,
        username: str | None,
        limit: int,
        cursor: str | None = None,
        tag: str | None = None,
        temp_only: bool = False,
    ) -> list[dict[str, Any]]:
        data = await self._execute(
            gql.POSTS_QUERY,
            {
                "username": username,
                "limit": limit,
                "cursor": cursor,
                "tag": tag,
                "temp_only": temp_only or None,
            },
            operation="글 목록 조회",
        )
        return data.get("posts") or []

    async def get_post(self, *, username: str, url_slug: str) -> dict[str, Any] | None:
        data = await self._execute(
            gql.POST_QUERY,
            {"username": username, "url_slug": url_slug},
            operation="글 조회",
        )
        return data.get("post")

    async def list_series(self, *, username: str) -> list[dict[str, Any]]:
        data = await self._execute(
            gql.SERIES_LIST_QUERY,
            {"username": username},
            operation="시리즈 목록 조회",
        )
        user = data.get("user")
        if not user:
            raise VelogError(f"시리즈 목록 조회: '{username}' 계정을 찾을 수 없습니다")
        return user.get("series_list") or []

    # ---------- 쓰기 ----------

    async def write_post(self, variables: dict[str, Any]) -> dict[str, Any]:
        data = await self._execute(gql.WRITE_POST_MUTATION, variables, operation="글 발행")
        return _require_write_result(data.get("writePost"), "글 발행")

    async def edit_post(self, variables: dict[str, Any]) -> dict[str, Any]:
        data = await self._execute(gql.EDIT_POST_MUTATION, variables, operation="글 수정")
        return _require_write_result(data.get("editPost"), "글 수정")

    async def remove_post(self, post_id: str) -> bool:
        data = await self._execute(
            gql.REMOVE_POST_MUTATION, {"id": post_id}, operation="글 삭제"
        )
        result = data.get("removePost")
        if result is None:
            raise VelogAuthError(
                "글 삭제: 벨로그가 결과를 돌려주지 않았습니다. "
                "토큰이 만료됐거나 내 글이 아닐 수 있습니다"
            )
        return bool(result)

    async def create_series(self, *, name: str, url_slug: str) -> dict[str, Any]:
        data = await self._execute(
            gql.CREATE_SERIES_MUTATION,
            {"name": name, "url_slug": url_slug},
            operation="시리즈 생성",
        )
        return _require_write_result(data.get("createSeries"), "시리즈 생성")


def _require_write_result(result: Any, operation: str) -> dict[str, Any]:
    """쓰기 뮤테이션의 null 결과를 인증 오류로 변환한다.

    벨로그는 미인증 상태에서 writePost·editPost 를 호출해도 GraphQL errors 없이
    data.writePost = null 만 돌려준다. 그대로 넘기면 '성공했는데 결과가 없다'로 보이므로
    여기서 명시적인 인증 오류로 바꾼다.
    """
    if not result:
        raise VelogAuthError(
            f"{operation}: 벨로그가 결과를 돌려주지 않았습니다. "
            "토큰이 만료됐을 가능성이 큽니다. `python scripts/login.py` 로 다시 로그인하세요"
        )
    return result


def _looks_like_auth_error(message: str) -> bool:
    lowered = message.lower()
    return any(
        keyword in lowered
        for keyword in ("not logged in", "unauthorized", "no permission", "forbidden")
    )
