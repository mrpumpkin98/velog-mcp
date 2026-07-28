"""벨로그 MCP 서버 (FastMCP, stdio)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from .browser_login import BrowserLoginError, PlaywrightMissingError, extract_tokens
from .client import VelogAuthError, VelogClient, VelogError
from .config import Settings, load_settings
from .markdown import parse_markdown_file, record_published_ids
from .token_store import save_tokens, store_path

INSTRUCTIONS = """\
벨로그(velog.io) 글을 발행·수정·조회하는 도구 모음입니다.

- 조회(velog_list_posts·velog_get_post·velog_list_series)는 인증 없이도 동작합니다.
- 발행·수정·삭제는 로그인이 필요합니다. 인증 오류가 나면 velog_login 을 호출하세요.
  벨로그에는 비밀번호 로그인이 없어 브라우저 창에서 사용자가 직접 인증해야 하며,
  한 번 로그인하면 토큰이 저장되고 이후 만료분은 자동 갱신됩니다.
- 로컬 마크다운 문서를 올릴 때는 velog_publish_markdown_file 을 쓰세요.
  프런트매터에 velog_post_id 가 기록되므로, 같은 파일을 다시 호출하면
  새 글이 생기지 않고 기존 글이 수정됩니다.
- 처음 발행할 때는 draft=True 로 임시저장해 결과를 확인한 뒤 공개하는 것을 권장합니다.
- 삭제는 되돌릴 수 없습니다. confirm=True 를 넘기기 전에 사용자에게 확인하세요.
"""

mcp = FastMCP("velog", instructions=INSTRUCTIONS, log_level="WARNING")

# stdio 트랜스포트에서는 로그가 대화 흐름을 가리므로 HTTP 요청 로그를 낮춘다.
logging.getLogger("httpx").setLevel(logging.WARNING)

_settings: Settings = load_settings()
_client: VelogClient | None = None
_cached_username: str | None = None

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, openWorldHint=True)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True)


def _get_client() -> VelogClient:
    global _client
    if _client is None:
        _client = VelogClient(_settings)
    return _client


async def shutdown() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def _reload_after_login() -> None:
    """로그인으로 토큰이 바뀌었으니 설정과 클라이언트를 새로 만든다.

    이 과정을 빼먹으면 같은 세션에서는 계속 옛 토큰을 쓰게 된다.
    """
    global _settings, _cached_username
    await shutdown()
    _settings = load_settings()
    _cached_username = None


def _require_credentials() -> None:
    if not _settings.has_credentials:
        raise ToolError(
            "벨로그 로그인 토큰이 없습니다. velog_login 도구를 호출하거나 "
            "`python scripts/login.py` 를 실행해 로그인하세요"
        )


async def _resolve_username(username: str | None) -> str:
    """조회 대상 계정을 정한다.

    명시한 값 → VELOG_USERNAME → 로그인한 계정 순으로 찾는다. 마지막 경로 덕분에
    토큰만 있으면 별도 설정 없이 내 글을 조회할 수 있다. 결과는 캐시한다.
    """
    global _cached_username

    explicit = (username or _settings.default_username or "").strip().lstrip("@")
    if explicit:
        return explicit
    if _cached_username:
        return _cached_username

    if not _settings.has_credentials:
        raise ToolError(
            "조회할 계정을 알 수 없습니다. username 을 지정하거나 VELOG_USERNAME 을 설정하거나, "
            "`python scripts/login.py` 로 로그인하세요"
        )

    try:
        auth = await _get_client().whoami()
    except VelogError as exc:
        raise _wrap(exc) from exc

    resolved = (auth or {}).get("username")
    if not resolved:
        raise ToolError(
            "로그인한 계정을 확인할 수 없습니다. username 을 직접 지정하거나 다시 로그인하세요"
        )
    _cached_username = resolved
    return resolved


def _post_url(post: dict[str, Any], username: str | None = None) -> str | None:
    owner = username or ((post.get("user") or {}).get("username"))
    slug = post.get("url_slug")
    if not owner or not slug:
        return None
    return f"https://velog.io/@{owner}/{slug}"


def _shape_post(post: dict[str, Any], *, username: str | None = None) -> dict[str, Any]:
    """응답을 도구 사용자가 읽기 쉬운 형태로 정리한다."""
    shaped = {
        "post_id": post.get("id"),
        "title": post.get("title"),
        "url_slug": post.get("url_slug"),
        "url": _post_url(post, username),
        "tags": post.get("tags") or [],
        "is_private": post.get("is_private"),
        "released_at": post.get("released_at"),
        "updated_at": post.get("updated_at"),
        "short_description": post.get("short_description"),
    }
    if "is_temp" in post:
        shaped["is_draft"] = post.get("is_temp")
    if post.get("series"):
        shaped["series"] = post["series"]
    if post.get("body") is not None:
        shaped["body"] = post["body"]
    return {k: v for k, v in shaped.items() if v is not None}


def _wrap(exc: VelogError) -> ToolError:
    return ToolError(str(exc))


# --------------------------------------------------------------------------- 조회


@mcp.tool(
    title="벨로그 계정 확인",
    description="현재 설정된 토큰으로 로그인되는 벨로그 계정을 확인합니다. 발행 전 인증 점검용입니다.",
    annotations=READ_ONLY,
)
async def velog_whoami() -> dict[str, Any]:
    if not _settings.has_credentials:
        return {
            "authenticated": False,
            "reason": (
                "저장된 토큰이 없습니다. velog_login 도구를 호출하거나 "
                "`python scripts/login.py` 를 실행해 로그인하세요"
            ),
            "default_username": _settings.default_username,
            "token_store": str(store_path()),
            "dry_run": _settings.dry_run,
        }

    client = _get_client()
    try:
        auth = await client.whoami()
    except VelogError as exc:
        raise _wrap(exc) from exc

    if not auth:
        return {
            "authenticated": False,
            "reason": (
                "토큰이 만료됐거나 잘못되었습니다. velog_login 도구로 다시 로그인하세요"
            ),
            "token_source": client.settings.token_source,
            "token_store": str(store_path()),
            "dry_run": _settings.dry_run,
        }
    return {
        "authenticated": True,
        "username": auth.get("username"),
        "email": auth.get("email"),
        "display_name": (auth.get("profile") or {}).get("display_name"),
        "token_source": client.settings.token_source,
        "dry_run": _settings.dry_run,
    }


@mcp.tool(
    title="벨로그 로그인",
    description=(
        "벨로그 로그인 창을 열어 토큰을 발급받아 저장합니다. 토큰이 만료돼 쓰기 도구가 "
        "인증 오류를 낼 때 이 도구를 호출하면 됩니다. 벨로그에는 비밀번호 로그인이 없어 "
        "브라우저에서 사용자가 직접 인증해야 하며, 한 번 로그인하면 프로필이 저장돼 "
        "다음부터는 headless=True 로 창 없이 갱신할 수 있습니다."
    ),
    annotations=WRITE,
)
async def velog_login(
    headless: Annotated[
        bool,
        Field(
            description=(
                "창을 띄우지 않고 저장된 프로필로 갱신만 시도. "
                "처음 로그인할 때는 False 여야 한다"
            )
        ),
    ] = False,
    timeout_sec: Annotated[
        int, Field(description="로그인 완료를 기다릴 시간(초)", ge=10, le=600)
    ] = 180,
    force: Annotated[
        bool, Field(description="이미 로그인돼 있어도 다시 로그인")
    ] = False,
) -> dict[str, Any]:
    # 이미 쓸 수 있는 상태면 굳이 브라우저를 띄우지 않는다.
    if not force and _settings.has_credentials:
        try:
            auth = await _get_client().whoami()
        except VelogError:
            auth = None
        if auth:
            return {
                "logged_in": True,
                "already_authenticated": True,
                "username": auth.get("username"),
                "message": "이미 로그인되어 있습니다. 다시 로그인하려면 force=True 로 호출하세요",
            }

    try:
        tokens = await extract_tokens(
            headless=headless,
            timeout_sec=timeout_sec,
            on_progress=lambda message: logging.getLogger(__name__).info(message),
        )
    except PlaywrightMissingError as exc:
        raise ToolError(str(exc)) from exc
    except BrowserLoginError as exc:
        raise ToolError(str(exc)) from exc

    path = save_tokens(
        access_token=tokens.get("access_token"),
        refresh_token=tokens.get("refresh_token"),
    )
    await _reload_after_login()

    try:
        auth = await _get_client().whoami()
    except VelogError as exc:
        raise _wrap(exc) from exc

    if not auth:
        raise ToolError(
            "토큰을 저장했지만 계정 확인에 실패했습니다. force=True 로 다시 로그인해 보세요"
        )

    return {
        "logged_in": True,
        "username": auth.get("username"),
        "display_name": (auth.get("profile") or {}).get("display_name"),
        "token_store": str(path),
        "has_refresh_token": bool(tokens.get("refresh_token")),
    }


@mcp.tool(
    title="벨로그 글 목록",
    description=(
        "벨로그 글 목록을 최신순으로 가져옵니다. username 을 생략하면 VELOG_USERNAME 을 씁니다. "
        "drafts_only=True 로 내 임시저장 글만 볼 수 있습니다(인증 필요)."
    ),
    annotations=READ_ONLY,
)
async def velog_list_posts(
    username: Annotated[str | None, Field(description="벨로그 계정명(@ 제외)")] = None,
    limit: Annotated[int, Field(description="가져올 개수", ge=1, le=50)] = 10,
    cursor: Annotated[
        str | None, Field(description="이어서 가져올 기준이 되는 글 UUID")
    ] = None,
    tag: Annotated[str | None, Field(description="특정 태그로 필터")] = None,
    drafts_only: Annotated[bool, Field(description="임시저장 글만 조회")] = False,
) -> dict[str, Any]:
    resolved = await _resolve_username(username)
    if drafts_only:
        _require_credentials()
    try:
        posts = await _get_client().list_posts(
            username=resolved,
            limit=limit,
            cursor=cursor,
            tag=tag,
            temp_only=drafts_only,
        )
    except VelogError as exc:
        raise _wrap(exc) from exc

    return {
        "username": resolved,
        "count": len(posts),
        "next_cursor": posts[-1].get("id") if posts else None,
        "posts": [_shape_post(p, username=resolved) for p in posts],
    }


@mcp.tool(
    title="벨로그 글 조회",
    description="url_slug 로 글 하나를 가져옵니다. 마크다운 본문(body)까지 포함합니다.",
    annotations=READ_ONLY,
)
async def velog_get_post(
    url_slug: Annotated[str, Field(description="글 URL 의 마지막 조각")],
    username: Annotated[str | None, Field(description="벨로그 계정명(@ 제외)")] = None,
) -> dict[str, Any]:
    resolved = await _resolve_username(username)
    try:
        post = await _get_client().get_post(username=resolved, url_slug=url_slug)
    except VelogError as exc:
        raise _wrap(exc) from exc

    if not post:
        raise ToolError(f"글을 찾을 수 없습니다: @{resolved}/{url_slug}")
    return _shape_post(post, username=resolved)


@mcp.tool(
    title="벨로그 시리즈 목록",
    description="시리즈 목록과 각 시리즈의 UUID를 가져옵니다. 발행 시 series_id 에 넣을 값입니다.",
    annotations=READ_ONLY,
)
async def velog_list_series(
    username: Annotated[str | None, Field(description="벨로그 계정명(@ 제외)")] = None,
) -> dict[str, Any]:
    resolved = await _resolve_username(username)
    try:
        series = await _get_client().list_series(username=resolved)
    except VelogError as exc:
        raise _wrap(exc) from exc
    return {"username": resolved, "count": len(series), "series": series}


# --------------------------------------------------------------------------- 쓰기


def _build_payload(
    *,
    title: str | None,
    body: str | None,
    tags: list[str] | None,
    url_slug: str | None,
    thumbnail: str | None,
    private: bool | None,
    draft: bool | None,
    series_id: str | None,
) -> dict[str, Any]:
    return {
        "title": title,
        "body": body,
        "tags": tags,
        "url_slug": url_slug,
        "thumbnail": thumbnail,
        "is_private": private,
        "is_temp": draft,
        "series_id": series_id,
        # 본문은 항상 마크다운으로 취급한다.
        "is_markdown": True,
        # meta 가 객체가 아니면 벨로그가 에러 없이 null 만 돌려준다(2026-07 실측).
        # 웹 에디터도 항상 {} 를 보낸다. 자세한 내용은 graphql.py 주석 참고.
        "meta": {},
    }


@mcp.tool(
    title="벨로그 글 발행",
    description=(
        "새 글을 발행합니다. body 는 마크다운입니다. "
        "draft=True 면 임시저장으로만 올라가고 공개되지 않으니, 확인이 필요할 때 사용하세요."
    ),
    annotations=WRITE,
)
async def velog_publish_post(
    title: Annotated[str, Field(description="글 제목", min_length=1)],
    body: Annotated[str, Field(description="마크다운 본문")],
    tags: Annotated[list[str] | None, Field(description="태그 목록")] = None,
    url_slug: Annotated[
        str | None, Field(description="URL 슬러그. 생략하면 벨로그가 제목으로 만든다")
    ] = None,
    thumbnail: Annotated[str | None, Field(description="썸네일 이미지 URL")] = None,
    private: Annotated[bool, Field(description="비공개 발행")] = False,
    draft: Annotated[bool, Field(description="임시저장(초안)으로 저장")] = False,
    series_id: Annotated[str | None, Field(description="시리즈 UUID")] = None,
) -> dict[str, Any]:
    _require_credentials()
    payload = _build_payload(
        title=title,
        body=body,
        tags=tags or [],
        url_slug=url_slug,
        thumbnail=thumbnail,
        private=private,
        draft=draft,
        series_id=series_id,
    )
    if _settings.dry_run:
        return {"dry_run": True, "would_send": payload}

    try:
        post = await _get_client().write_post(payload)
    except VelogError as exc:
        raise _wrap(exc) from exc
    return {"created": True, **_shape_post(post)}


@mcp.tool(
    title="벨로그 글 수정",
    description=(
        "기존 글을 수정합니다. post_id 는 필수이고, 나머지는 넘긴 항목만 바뀝니다. "
        "본문 일부만 고칠 때도 body 는 전체를 보내야 합니다(부분 수정 불가)."
    ),
    annotations=WRITE,
)
async def velog_update_post(
    post_id: Annotated[str, Field(description="글 UUID")],
    title: Annotated[str | None, Field(description="새 제목")] = None,
    body: Annotated[str | None, Field(description="새 마크다운 본문(전체)")] = None,
    tags: Annotated[list[str] | None, Field(description="새 태그 목록(전체 교체)")] = None,
    url_slug: Annotated[str | None, Field(description="새 URL 슬러그")] = None,
    thumbnail: Annotated[str | None, Field(description="새 썸네일 URL")] = None,
    private: Annotated[bool | None, Field(description="비공개 여부")] = None,
    draft: Annotated[bool | None, Field(description="임시저장 여부")] = None,
    series_id: Annotated[str | None, Field(description="시리즈 UUID")] = None,
) -> dict[str, Any]:
    _require_credentials()
    payload = _build_payload(
        title=title,
        body=body,
        tags=tags,
        url_slug=url_slug,
        thumbnail=thumbnail,
        private=private,
        draft=draft,
        series_id=series_id,
    )
    payload["id"] = post_id
    if _settings.dry_run:
        return {"dry_run": True, "would_send": payload}

    try:
        post = await _get_client().edit_post(payload)
    except VelogError as exc:
        raise _wrap(exc) from exc
    return {"updated": True, **_shape_post(post)}


@mcp.tool(
    title="벨로그 글 삭제",
    description=(
        "글을 삭제합니다. 복구할 수 없으므로 confirm=True 를 명시해야 실행됩니다."
    ),
    annotations=DESTRUCTIVE,
)
async def velog_delete_post(
    post_id: Annotated[str, Field(description="삭제할 글 UUID")],
    confirm: Annotated[bool, Field(description="삭제를 확인. True 여야 실행된다")] = False,
) -> dict[str, Any]:
    if not confirm:
        raise ToolError(
            "삭제는 되돌릴 수 없습니다. 정말 지우려면 confirm=True 로 다시 호출하세요"
        )
    _require_credentials()
    if _settings.dry_run:
        return {"dry_run": True, "would_delete": post_id}

    try:
        removed = await _get_client().remove_post(post_id)
    except VelogError as exc:
        raise _wrap(exc) from exc
    return {"deleted": removed, "post_id": post_id}


@mcp.tool(
    title="벨로그 시리즈 생성",
    description="새 시리즈를 만들고 UUID를 돌려줍니다. 발행 시 series_id 로 사용하세요.",
    annotations=WRITE,
)
async def velog_create_series(
    name: Annotated[str, Field(description="시리즈 이름", min_length=1)],
    url_slug: Annotated[str, Field(description="시리즈 URL 슬러그", min_length=1)],
) -> dict[str, Any]:
    _require_credentials()
    if _settings.dry_run:
        return {"dry_run": True, "would_create": {"name": name, "url_slug": url_slug}}

    try:
        series = await _get_client().create_series(name=name, url_slug=url_slug)
    except VelogError as exc:
        raise _wrap(exc) from exc
    return {"created": True, **series}


@mcp.tool(
    title="마크다운 파일 발행",
    description=(
        "로컬 마크다운 파일을 벨로그에 올립니다. 프런트매터(title·tags·slug·series_id 등)를 읽고, "
        "발행 후 파일에 velog_post_id 를 기록합니다. 같은 파일을 다시 호출하면 새 글을 만들지 않고 "
        "기존 글을 수정하므로, 문서를 고칠 때마다 그대로 재실행하면 됩니다."
    ),
    annotations=WRITE,
)
async def velog_publish_markdown_file(
    file_path: Annotated[str, Field(description="마크다운 파일의 절대 경로")],
    draft: Annotated[
        bool | None,
        Field(description="임시저장 여부. 지정하면 프런트매터 draft 값을 덮어쓴다"),
    ] = None,
    private: Annotated[
        bool | None, Field(description="비공개 여부. 지정하면 프런트매터 값을 덮어쓴다")
    ] = None,
    series_id: Annotated[
        str | None, Field(description="시리즈 UUID. 지정하면 프런트매터 값을 덮어쓴다")
    ] = None,
    update_frontmatter: Annotated[
        bool, Field(description="발행 후 파일에 velog_post_id·velog_url 기록")
    ] = True,
) -> dict[str, Any]:
    _require_credentials()

    path = Path(file_path).expanduser()
    if not path.is_absolute():
        raise ToolError(f"절대 경로로 지정해야 합니다: {file_path}")
    try:
        document = parse_markdown_file(path)
    except (FileNotFoundError, OSError, UnicodeDecodeError) as exc:
        raise ToolError(f"마크다운 파일을 읽을 수 없습니다: {exc}") from exc

    if not document.body.strip():
        raise ToolError(f"본문이 비어 있습니다: {path}")

    payload = _build_payload(
        title=document.title,
        body=document.body,
        tags=document.tags,
        url_slug=document.url_slug,
        thumbnail=document.thumbnail,
        private=document.is_private if private is None else private,
        draft=document.is_draft if draft is None else draft,
        series_id=series_id or document.series_id,
    )

    is_update = bool(document.existing_post_id)
    if is_update:
        payload["id"] = document.existing_post_id

    if _settings.dry_run:
        return {
            "dry_run": True,
            "mode": "update" if is_update else "create",
            "source_file": str(path),
            "would_send": payload,
        }

    client = _get_client()
    try:
        post = await (client.edit_post(payload) if is_update else client.write_post(payload))
    except VelogAuthError as exc:
        raise _wrap(exc) from exc
    except VelogError as exc:
        raise _wrap(exc) from exc

    shaped = _shape_post(post)
    frontmatter_written = False
    if update_frontmatter and shaped.get("post_id"):
        try:
            record_published_ids(
                path, post_id=str(shaped["post_id"]), url=shaped.get("url")
            )
            frontmatter_written = True
        except OSError:
            # 발행은 성공했으므로 실패로 만들지 않고 결과에만 표시한다.
            frontmatter_written = False

    return {
        "mode": "update" if is_update else "create",
        "source_file": str(path),
        "frontmatter_updated": frontmatter_written,
        **shaped,
    }
