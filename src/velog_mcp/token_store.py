"""토큰 저장소.

벨로그 access_token 은 수명이 짧고, 요청을 보낼 때마다 서버가 Set-Cookie 로 새 값을
내려줄 수 있다. 그 값을 프로세스 메모리에만 두면 서버를 재시작할 때마다 만료된 토큰으로
돌아가므로, 홈 디렉터리의 JSON 파일에 보관한다.

환경변수보다 이 파일이 우선한다. 환경변수는 '최초 씨앗값'이고, 이후 갱신분은 파일에 쌓인다.
파일 권한은 0600 으로 두어 본인만 읽을 수 있게 한다.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_STORE_PATH = Path.home() / ".velog-mcp" / "tokens.json"


def store_path() -> Path:
    override = (os.getenv("VELOG_TOKEN_STORE") or "").strip()
    return Path(override).expanduser() if override else DEFAULT_STORE_PATH


@dataclass(frozen=True)
class StoredTokens:
    access_token: str | None = None
    refresh_token: str | None = None
    updated_at: str | None = None

    @property
    def is_empty(self) -> bool:
        return not (self.access_token or self.refresh_token)


def load_tokens(path: Path | None = None) -> StoredTokens:
    target = path or store_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return StoredTokens()

    if not isinstance(raw, dict):
        return StoredTokens()
    return StoredTokens(
        access_token=_clean(raw.get("access_token")),
        refresh_token=_clean(raw.get("refresh_token")),
        updated_at=_clean(raw.get("updated_at")),
    )


def save_tokens(
    *,
    access_token: str | None,
    refresh_token: str | None,
    path: Path | None = None,
) -> Path:
    """토큰을 원자적으로 저장한다.

    같은 디렉터리에 임시 파일을 쓴 뒤 교체해, 쓰는 중에 서버가 죽어도
    반쪽짜리 JSON 이 남지 않게 한다.
    """
    target = path or store_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".tokens-", suffix=".json")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    return target


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
