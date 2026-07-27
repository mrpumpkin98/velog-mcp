"""환경변수 + 토큰 저장소 기반 설정.

설정값은 프로세스 환경변수에서만 읽는다. MCP 서버는 클라이언트가 임의의 작업
디렉터리에서 띄우므로 프로젝트 폴더의 .env 를 찾는 방식은 조용히 무시되기 쉽다.
설정은 클라이언트 설정 파일의 env 블록에 넣는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace

from .token_store import load_tokens

DEFAULT_ENDPOINT = "https://v2.velog.io/graphql"

_TRUTHY = {"1", "true", "yes", "on"}


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in _TRUTHY


@dataclass(frozen=True)
class Settings:
    access_token: str | None
    refresh_token: str | None
    default_username: str | None
    endpoint: str
    dry_run: bool
    persist_tokens: bool
    """토큰 출처. 진단 메시지에만 쓴다."""
    token_source: str = "none"

    @property
    def has_credentials(self) -> bool:
        return bool(self.access_token or self.refresh_token)

    def cookie_header(self) -> str | None:
        """벨로그는 access_token·refresh_token 쿠키로 인증한다.

        브라우저와 동일하게 두 값을 함께 보낸다. access_token 이 만료됐을 때
        벨로그 서버가 refresh_token 을 보고 새 access_token 을 Set-Cookie 로 내려준다.
        """
        parts = []
        if self.access_token:
            parts.append(f"access_token={self.access_token}")
        if self.refresh_token:
            parts.append(f"refresh_token={self.refresh_token}")
        return "; ".join(parts) if parts else None

    def with_tokens(self, *, access_token: str | None, refresh_token: str | None) -> Settings:
        return replace(self, access_token=access_token, refresh_token=refresh_token)


def load_settings() -> Settings:
    env_access = (os.getenv("VELOG_ACCESS_TOKEN") or "").strip() or None
    env_refresh = (os.getenv("VELOG_REFRESH_TOKEN") or "").strip() or None

    # 저장소에는 갱신된 최신 토큰이 들어 있으므로 환경변수보다 우선한다.
    # 환경변수는 저장소가 비어 있을 때의 씨앗값 역할만 한다.
    stored = load_tokens()
    if stored.is_empty:
        access, refresh, source = env_access, env_refresh, "env" if env_access or env_refresh else "none"
    else:
        access = stored.access_token or env_access
        refresh = stored.refresh_token or env_refresh
        source = "store"

    return Settings(
        access_token=access,
        refresh_token=refresh,
        default_username=(os.getenv("VELOG_USERNAME") or "").strip().lstrip("@") or None,
        endpoint=(os.getenv("VELOG_GRAPHQL_ENDPOINT") or "").strip() or DEFAULT_ENDPOINT,
        dry_run=_flag("VELOG_DRY_RUN"),
        persist_tokens=_flag("VELOG_PERSIST_TOKENS", default=True),
        token_source=source,
    )
