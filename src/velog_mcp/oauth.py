"""MCP 클라이언트용 OAuth 인증 서버.

왜 필요한가
    Cursor 는 MCP 서버가 OAuth 를 지원할 때만 설정 화면에 Connect/Logout 버튼을 그린다.
    그 버튼을 누르면 브라우저가 열려 인증이 끝나므로, 사용자가 로그인을 위해 대화를
    시작할 필요가 없다. 다만 이 방식은 stdio 가 아니라 HTTP 트랜스포트에서만 동작한다.

무엇을 인증하는가 (오해하기 쉬운 부분)
    벨로그는 서드파티용 OAuth 제공자가 없다. 그래서 여기서 발급하는 토큰은
    '벨로그 토큰'이 아니라 **이 MCP 서버에 접근할 권한**을 뜻하는 자체 토큰이다.
    실제 벨로그 인증은 예전과 똑같이 브라우저에서 쿠키를 받아오는 방식이고,
    그 쿠키는 서버 쪽 token_store 에만 남는다. 즉 이 파일은 다음 두 가지를 잇는다.

        Cursor  <--(OAuth: 우리가 발급한 토큰)-->  이 서버  <--(쿠키)-->  벨로그

흐름
    1. Cursor 가 /authorize 로 보낸다
    2. authorize() 는 로그인 트랜잭션을 만들고 /velog/login?txn=... 로 보낸다
    3. 그 라우트(http_app.py)가 벨로그 로그인을 처리하고 complete_login() 을 부른다
    4. Cursor 의 redirect_uri 로 code 를 돌려주고, Cursor 가 /token 에서 교환한다

리다이렉트 URL 을 하드코딩하지 않는 이유
    Cursor 가 쓰는 콜백 주소는 문서와 실제가 어긋난다는 보고가 있다. 동적 클라이언트
    등록(DCR)을 켜두면 Cursor 가 등록 시점에 자기 redirect_uris 를 알려주므로
    우리가 그 값을 알아야 할 이유가 없어진다.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from .token_store import store_path

logger = logging.getLogger(__name__)

SCOPES = ["velog:read", "velog:write"]

_AUTH_CODE_TTL_SEC = 300
_ACCESS_TOKEN_TTL_SEC = 60 * 60 * 24 * 30
_LOGIN_TXN_TTL_SEC = 600

# Cursor 는 재접속할 때마다 클라이언트를 새로 등록한다(실측: 여덟 번 붙어 여덟 건).
# 그대로 쌓으면 파일이 끝없이 커지므로 상한을 두고 오래된 것부터 버린다.
# 쓰는 쪽은 늘 가장 최근 항목이라 넉넉한 값이면 실사용에 영향이 없다.
_MAX_CLIENTS = 20
_MAX_TOKEN_SETS = 20


def _state_dir() -> Path:
    """OAuth 상태를 벨로그 토큰과 같은 디렉터리에 둔다."""
    override = (os.getenv("VELOG_OAUTH_STATE_DIR") or "").strip()
    if override:
        return Path(override).expanduser()
    return store_path().parent


@dataclass
class LoginTransaction:
    """진행 중인 벨로그 로그인 한 건.

    Cursor 의 요청 정보를 들고 있다가, 로그인이 끝나면 code 를 만들어 돌려보낸다.
    """

    txn_id: str
    client_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    code_challenge: str
    scopes: list[str]
    state: str | None
    resource: str | None
    created_at: float = field(default_factory=time.time)

    @property
    def is_expired(self) -> bool:
        return time.time() - self.created_at > _LOGIN_TXN_TTL_SEC


class _JsonStore:
    """작은 JSON 파일 저장소.

    서버를 재시작해도 등록된 클라이언트와 발급한 토큰이 남아 있어야 한다.
    메모리에만 두면 재시작할 때마다 Cursor 가 '로그아웃' 상태로 돌아간다.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return
        if isinstance(raw, dict):
            self._data = raw

    def _flush(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.chmod(tmp, 0o600)
            os.replace(tmp, self._path)
        except OSError as exc:
            # 저장 실패가 인증 자체를 막지는 않게 한다. 이번 프로세스에서는 메모리로 버틴다.
            logger.warning("OAuth 상태를 저장하지 못했습니다 (%s): %s", self._path.name, exc)

    def get(self, key: str) -> Any:
        return self._data.get(key)

    def put(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._flush()

    def drop(self, key: str, *, flush: bool = True) -> None:
        if self._data.pop(key, None) is not None and flush:
            self._flush()

    def flush(self) -> None:
        self._flush()

    def keys(self) -> list[str]:
        """저장 순서대로 돌려준다.

        JSON 왕복에도 dict 삽입 순서가 유지되므로, 앞쪽이 오래된 항목이다.
        따로 타임스탬프를 두지 않고 이 순서를 정리 기준으로 쓴다.
        """
        return list(self._data)

    def items(self) -> list[tuple[str, Any]]:
        return list(self._data.items())


class VelogOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    """벨로그 브라우저 로그인을 OAuth 인증 코드 흐름으로 감싼다."""

    def __init__(self, *, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        state = _state_dir()
        self._clients = _JsonStore(state / "oauth-clients.json")
        self._tokens = _JsonStore(state / "oauth-tokens.json")
        self._codes: dict[str, AuthorizationCode] = {}
        self._logins: dict[str, LoginTransaction] = {}

    # ---------- 클라이언트 등록 (DCR) ----------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        raw = self._clients.get(client_id)
        if not raw:
            return None
        try:
            return OAuthClientInformationFull.model_validate(raw)
        except ValueError:
            self._clients.drop(client_id)
            return None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self._clients.put(client_info.client_id, client_info.model_dump(mode="json"))
        self._evict_clients()
        logger.info(
            "OAuth 클라이언트를 등록했습니다: %s (redirect_uris=%s)",
            client_info.client_id,
            [str(u) for u in client_info.redirect_uris or []],
        )

    # ---------- 인증 ----------

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        """벨로그 로그인 페이지로 보낼 URL 을 돌려준다.

        여기서 바로 브라우저를 띄우지 않는다. 이 함수는 리다이렉트 URL 만 만들고,
        실제 로그인은 사용자가 그 주소를 열었을 때 http_app 쪽에서 진행한다.
        """
        self._sweep()
        txn = LoginTransaction(
            txn_id=secrets.token_urlsafe(32),
            client_id=client.client_id,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            code_challenge=params.code_challenge,
            scopes=params.scopes or list(SCOPES),
            state=params.state,
            resource=params.resource,
        )
        self._logins[txn.txn_id] = txn
        return f"{self._base_url}/velog/login?txn={txn.txn_id}"

    def get_login(self, txn_id: str) -> LoginTransaction | None:
        txn = self._logins.get(txn_id)
        if txn and txn.is_expired:
            self._logins.pop(txn_id, None)
            return None
        return txn

    def complete_login(self, txn: LoginTransaction) -> str:
        """로그인 성공. 인증 코드를 만들어 Cursor 로 돌아갈 URL 을 돌려준다."""
        code = AuthorizationCode(
            code=secrets.token_urlsafe(32),
            scopes=txn.scopes,
            expires_at=time.time() + _AUTH_CODE_TTL_SEC,
            client_id=txn.client_id,
            code_challenge=txn.code_challenge,
            redirect_uri=txn.redirect_uri,  # type: ignore[arg-type]
            redirect_uri_provided_explicitly=txn.redirect_uri_provided_explicitly,
            resource=txn.resource,
            subject="velog-local-user",
        )
        self._codes[code.code] = code
        self._logins.pop(txn.txn_id, None)
        return construct_redirect_uri(txn.redirect_uri, code=code.code, state=txn.state)

    def fail_login(self, txn: LoginTransaction, *, reason: str) -> str:
        """로그인 실패. OAuth 규격대로 error 를 붙여 되돌려보낸다."""
        self._logins.pop(txn.txn_id, None)
        return construct_redirect_uri(
            txn.redirect_uri,
            error="access_denied",
            error_description=reason,
            state=txn.state,
        )

    # ---------- 코드·토큰 교환 ----------

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        code = self._codes.get(authorization_code)
        if not code:
            return None
        if code.client_id != client.client_id or code.expires_at < time.time():
            self._codes.pop(authorization_code, None)
            return None
        return code

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        self._codes.pop(authorization_code.code, None)
        return self._issue(client_id=client.client_id, scopes=authorization_code.scopes)

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        raw = self._tokens.get(f"refresh:{refresh_token}")
        if not raw or raw.get("client_id") != client.client_id:
            return None
        return RefreshToken.model_validate(raw)

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        # 규격 권고대로 access·refresh 를 함께 회전시킨다.
        self._tokens.drop(f"refresh:{refresh_token.token}")
        return self._issue(client_id=client.client_id, scopes=scopes or refresh_token.scopes)

    async def load_access_token(self, token: str) -> AccessToken | None:
        raw = self._tokens.get(f"access:{token}")
        if not raw:
            return None
        access = AccessToken.model_validate(raw)
        if access.expires_at is not None and access.expires_at < time.time():
            self._tokens.drop(f"access:{token}")
            return None
        return access

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """Logout 을 눌렀을 때 호출된다. 짝이 되는 토큰까지 함께 지운다."""
        given_is_access = isinstance(token, AccessToken)
        pair = self._tokens.get(f"pair:{token.token}")
        access = token.token if given_is_access else (pair if isinstance(pair, str) else None)

        if access:
            self._drop_token_set(access)
        else:
            # 짝을 못 찾으면 받은 것만 지운다. 지우지 않고 남기는 쪽이 더 위험하다.
            self._tokens.drop(f"{'access' if given_is_access else 'refresh'}:{token.token}", flush=False)
            self._tokens.drop(f"pair:{token.token}")
        logger.info("OAuth 토큰을 폐기했습니다")

    # ---------- 내부 ----------

    def _issue(self, *, client_id: str, scopes: list[str]) -> OAuthToken:
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + _ACCESS_TOKEN_TTL_SEC

        self._tokens.put(
            f"access:{access}",
            AccessToken(
                token=access,
                client_id=client_id,
                scopes=scopes,
                expires_at=expires_at,
                subject="velog-local-user",
            ).model_dump(mode="json"),
        )
        self._tokens.put(
            f"refresh:{refresh}",
            RefreshToken(token=refresh, client_id=client_id, scopes=scopes).model_dump(mode="json"),
        )
        # revoke 시 짝을 찾기 위한 양방향 링크
        self._tokens.put(f"pair:{access}", refresh)
        self._tokens.put(f"pair:{refresh}", access)
        self._evict_tokens()

        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=_ACCESS_TOKEN_TTL_SEC,
            refresh_token=refresh,
            scope=" ".join(scopes),
        )

    def _drop_token_set(self, access: str) -> None:
        """access 토큰과 그 짝인 refresh, 연결 정보까지 한 번에 지운다."""
        refresh = self._tokens.get(f"pair:{access}")
        self._tokens.drop(f"access:{access}", flush=False)
        self._tokens.drop(f"pair:{access}", flush=False)
        if isinstance(refresh, str):
            self._tokens.drop(f"refresh:{refresh}", flush=False)
            self._tokens.drop(f"pair:{refresh}", flush=False)
        self._tokens.flush()

    def _evict_clients(self) -> None:
        keys = self._clients.keys()
        for key in keys[: max(0, len(keys) - _MAX_CLIENTS)]:
            self._clients.drop(key, flush=False)
        self._clients.flush()

    def _evict_tokens(self) -> None:
        now = time.time()

        # 만료된 것을 먼저 버린다. 상한에 걸리기 전에 정리되는 편이 자연스럽다.
        for key, value in self._tokens.items():
            if not key.startswith("access:") or not isinstance(value, dict):
                continue
            expires_at = value.get("expires_at")
            if expires_at is not None and expires_at < now:
                self._drop_token_set(key.split(":", 1)[1])

        access_keys = [k for k in self._tokens.keys() if k.startswith("access:")]
        for key in access_keys[: max(0, len(access_keys) - _MAX_TOKEN_SETS)]:
            self._drop_token_set(key.split(":", 1)[1])

    def _sweep(self) -> None:
        for txn_id, txn in list(self._logins.items()):
            if txn.is_expired:
                self._logins.pop(txn_id, None)
        now = time.time()
        for code, value in list(self._codes.items()):
            if value.expires_at < now:
                self._codes.pop(code, None)
