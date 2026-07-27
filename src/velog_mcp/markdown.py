"""로컬 마크다운 파일 → 벨로그 글 변환.

프런트매터로 제목·태그·시리즈를 지정하고, 발행 뒤에는 글 id 를 파일에 다시 적어
같은 파일을 재실행하면 새 글이 아니라 기존 글이 수정되게 한다.

지원하는 프런트매터 키
    title           제목. 없으면 첫 번째 `# 제목` 을, 그것도 없으면 파일명을 쓴다.
    tags            리스트 또는 쉼표로 구분한 문자열
    slug/url_slug   URL 슬러그
    thumbnail       썸네일 이미지 URL
    private         true 면 비공개 발행
    draft           true 면 임시저장(초안)
    series_id       시리즈 UUID
    velog_post_id   발행 후 도구가 기록. 있으면 수정 모드로 동작한다.
    velog_url       발행 후 도구가 기록(사람이 보기 위한 값)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import frontmatter

POST_ID_KEY = "velog_post_id"
URL_KEY = "velog_url"

_H1_PATTERN = re.compile(r"^\s{0,3}#\s+(?P<title>.+?)\s*$", re.MULTILINE)


@dataclass
class ParsedDocument:
    path: Path
    title: str
    body: str
    tags: list[str] = field(default_factory=list)
    url_slug: str | None = None
    thumbnail: str | None = None
    is_private: bool = False
    is_draft: bool = False
    series_id: str | None = None
    existing_post_id: str | None = None


def parse_markdown_file(path: Path) -> ParsedDocument:
    if not path.is_file():
        raise FileNotFoundError(f"마크다운 파일을 찾을 수 없습니다: {path}")

    document = frontmatter.loads(path.read_text(encoding="utf-8"))
    meta: dict[str, Any] = dict(document.metadata)
    body = document.content.strip()

    title = _clean_str(meta.get("title"))
    if title:
        # 제목을 프런트매터에서 받았으므로 본문은 손대지 않는다.
        final_body = body
    else:
        title, final_body = _extract_title_from_body(body, fallback=path.stem)

    return ParsedDocument(
        path=path,
        title=title,
        body=final_body,
        tags=_normalize_tags(meta.get("tags")),
        url_slug=_clean_str(meta.get("slug")) or _clean_str(meta.get("url_slug")),
        thumbnail=_clean_str(meta.get("thumbnail")),
        is_private=bool(meta.get("private", False)),
        is_draft=bool(meta.get("draft", False)),
        series_id=_clean_str(meta.get("series_id")),
        existing_post_id=_clean_str(meta.get(POST_ID_KEY)),
    )


def record_published_ids(path: Path, *, post_id: str, url: str | None) -> None:
    """발행 결과(글 id·URL)를 프런트매터에 적어 다음 실행이 수정 모드가 되게 한다."""
    document = frontmatter.loads(path.read_text(encoding="utf-8"))
    document[POST_ID_KEY] = post_id
    if url:
        document[URL_KEY] = url
    path.write_text(frontmatter.dumps(document) + "\n", encoding="utf-8")


def _extract_title_from_body(body: str, *, fallback: str) -> tuple[str, str]:
    """첫 H1 을 제목으로 승격하고 본문에서 제거한다.

    벨로그는 제목을 본문과 따로 렌더링하므로, H1 을 남겨두면 제목이 두 번 보인다.
    """
    match = _H1_PATTERN.search(body)
    if not match:
        return fallback, body

    title = match.group("title").strip()
    stripped = (body[: match.start()] + body[match.end() :]).strip()
    return title, stripped


def _normalize_tags(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        candidates = raw.split(",")
    elif isinstance(raw, (list, tuple, set)):
        candidates = list(raw)
    else:
        return []

    tags: list[str] = []
    for candidate in candidates:
        tag = str(candidate).strip()
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
