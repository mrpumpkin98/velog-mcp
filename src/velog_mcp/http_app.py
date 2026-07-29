"""HTTP(streamable-http) 트랜스포트 + 벨로그 로그인 콜백.

stdio 모드에서는 이 파일이 전혀 쓰이지 않는다. HTTP 모드에서만 OAuth 라우트가 붙고,
그래야 Cursor 설정 화면에 Connect 버튼이 생긴다(자세한 배경은 oauth.py 주석 참고).

라우트
    /mcp                        MCP 엔드포인트 (Bearer 토큰 필요)
    /.well-known/...            SDK 가 만들어주는 OAuth 메타데이터·authorize·token·register
    /velog/login?txn=           Connect 를 눌렀을 때 브라우저가 열리는 화면
    /velog/login/start?txn=     그 화면이 호출하는 실제 로그인 (벨로그 창을 띄운다)
"""

from __future__ import annotations

import logging

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from .browser_login import BrowserLoginError, extract_tokens
from .oauth import SCOPES, VelogOAuthProvider
from .server import _reload_after_login
from .token_store import save_tokens

logger = logging.getLogger(__name__)

_LOGIN_TIMEOUT_SEC = 180


def build_auth(base_url: str) -> tuple[VelogOAuthProvider, AuthSettings]:
    provider = VelogOAuthProvider(base_url=base_url)
    settings = AuthSettings(
        issuer_url=AnyHttpUrl(base_url),
        resource_server_url=AnyHttpUrl(f"{base_url.rstrip('/')}/mcp"),
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=list(SCOPES),
            default_scopes=list(SCOPES),
        ),
        revocation_options=RevocationOptions(enabled=True),
        # 비워둔다. 이 SDK 는 required_scopes 를 리소스 메타데이터의 scopes_supported 로도
        # 쓰기 때문에(fastmcp/server.py), 값을 채우면 '알린다'가 아니라 '없으면 거절한다'가 된다.
        # 클라이언트가 스코프를 일부만 요청해도 붙게 두는 편이 안전하다. 어차피 이 서버의
        # 실질적인 관문은 토큰 보유 여부이고, 쓸 수 있는 스코프 목록은 인증 서버
        # 메타데이터에서 이미 알려준다.
        required_scopes=[],
    )
    return provider, settings


def attach_auth(mcp, provider: VelogOAuthProvider, settings: AuthSettings) -> None:
    """이미 만들어진 FastMCP 인스턴스에 인증을 붙인다.

    FastMCP 는 인증을 생성자에서만 받는다. 그런데 server.py 의 `mcp` 는 모든 도구가
    데코레이터로 매달리는 대상이라 임포트 시점에 이미 만들어져 있어야 한다.
    생성자에 넘기려면 도구 등록 구조를 뒤집어야 하고, 그러면 잘 돌아가는 stdio 경로가
    위험해진다. 그래서 생성자가 하는 일(FastMCP.__init__ 의 auth 처리와 같다)을
    여기서 그대로 재현한다. SDK 내부 속성에 손대는 만큼, 이름이 바뀌면 즉시 알 수 있게
    조용히 넘기지 않고 예외를 던진다.
    """
    from mcp.server.auth.provider import ProviderTokenVerifier

    for attr in ("_auth_server_provider", "_token_verifier"):
        if not hasattr(mcp, attr):
            raise RuntimeError(
                f"이 SDK 버전에는 FastMCP.{attr} 가 없습니다. "
                "mcp 패키지가 올라가면서 인증 연결 방식이 바뀐 것 같습니다"
            )

    mcp.settings.auth = settings
    mcp._auth_server_provider = provider
    mcp._token_verifier = ProviderTokenVerifier(provider)


def register_login_routes(mcp, provider: VelogOAuthProvider) -> None:
    """Connect 버튼을 눌렀을 때 사용자가 보게 될 화면을 등록한다."""

    @mcp.custom_route("/velog/login", methods=["GET"])
    async def velog_login_page(request: Request):
        txn_id = request.query_params.get("txn", "")
        txn = provider.get_login(txn_id)
        if not txn:
            return HTMLResponse(
                _page("연결할 수 없습니다", "요청이 만료됐습니다. Cursor 에서 Connect 를 다시 눌러주세요."),
                status_code=400,
            )

        # 이미 쓸 수 있는 토큰이 있으면 창을 띄우지 않고 바로 끝낸다.
        if await _already_authenticated():
            logger.info("저장된 벨로그 토큰이 유효해 로그인 창 없이 연결합니다")
            return RedirectResponse(provider.complete_login(txn), status_code=302)

        return HTMLResponse(_login_page(txn_id))

    @mcp.custom_route("/velog/login/start", methods=["POST"])
    async def velog_login_start(request: Request):
        """벨로그 로그인 창을 띄우고, 끝나면 돌아갈 주소를 알려준다.

        로그인은 사람이 하는 일이라 최대 3분까지 걸린다. 그 시간 동안 이 요청은
        열린 채로 기다린다. 페이지가 fetch 로 부르고 응답이 오면 이동한다.
        """
        txn_id = request.query_params.get("txn", "")
        txn = provider.get_login(txn_id)
        if not txn:
            return JSONResponse({"error": "요청이 만료됐습니다"}, status_code=400)

        try:
            tokens = await extract_tokens(headless=False, timeout_sec=_LOGIN_TIMEOUT_SEC)
        except BrowserLoginError as exc:
            logger.warning("벨로그 로그인 실패: %s", exc)
            return JSONResponse({"redirect": provider.fail_login(txn, reason=str(exc))})

        save_tokens(
            access_token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
        )
        await _reload_after_login()
        logger.info("벨로그 로그인 완료. OAuth 인증 코드를 발급합니다")
        return JSONResponse({"redirect": provider.complete_login(txn)})


async def _already_authenticated() -> bool:
    """저장된 토큰으로 벨로그가 나를 알아보는지 확인한다."""
    from .client import VelogClient, VelogError
    from .config import load_settings

    settings = load_settings()
    if not settings.has_credentials:
        return False
    client = VelogClient(settings)
    try:
        return bool(await client.whoami())
    except VelogError:
        return False
    finally:
        await client.aclose()


def _page(title: str, message: str, *, extra: str = "") -> str:
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>{title} · velog-mcp</title>
<style>
  body {{ margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         background:#f8f9fa; font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif;
         color:#212529; }}
  .card {{ background:#fff; padding:44px 48px; border-radius:14px; max-width:460px;
          box-shadow:0 4px 24px rgba(0,0,0,.07); text-align:center; }}
  h1 {{ margin:0 0 14px; font-size:21px; }}
  p {{ margin:0; color:#495057; line-height:1.7; font-size:15px; }}
  .spinner {{ width:26px; height:26px; margin:0 auto 22px; border:3px solid #e9ecef;
             border-top-color:#20c997; border-radius:50%; animation:spin .8s linear infinite; }}
  @keyframes spin {{ to {{ transform:rotate(360deg); }} }}
  .err {{ color:#e03131; }}
</style></head>
<body><div class="card"><h1>{title}</h1><p>{message}</p>{extra}</div></body></html>"""


def _login_page(txn_id: str) -> str:
    body = _page(
        "벨로그 로그인",
        "로그인 창이 열립니다. 평소처럼 로그인하면 이 창이 저절로 닫힙니다.<br>"
        "벨로그에는 비밀번호 로그인이 없어 이메일 링크 또는 소셜 계정을 씁니다.",
        extra='<div class="spinner" id="sp"></div>',
    )
    script = f"""
<script>
fetch("/velog/login/start?txn=" + encodeURIComponent({txn_id!r}), {{ method: "POST" }})
  .then(r => r.json())
  .then(d => {{
    if (d.redirect) {{ location.replace(d.redirect); return; }}
    fail(d.error || "로그인에 실패했습니다");
  }})
  .catch(e => fail(String(e)));

function fail(msg) {{
  document.querySelector("h1").textContent = "로그인하지 못했습니다";
  document.querySelector("h1").className = "err";
  document.querySelector("p").textContent = msg;
  const sp = document.getElementById("sp");
  if (sp) sp.remove();
}}
</script>"""
    return body.replace("</body>", f"{script}</body>")
