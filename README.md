# velog-mcp

> 에이전트에게 **"이 문서 벨로그에 올려줘"** 라고 말하면 되는 MCP 서버

로컬 마크다운 파일을 [벨로그](https://velog.io)에 발행합니다. 발행하면 파일에 글 id가 적히고, **같은 파일을 다시 올리면 새 글이 생기는 대신 그 글이 수정됩니다.** Cursor·Claude Desktop 등 MCP 클라이언트에 그대로 붙습니다.

> ⚠️ **벨로그와 무관한 개인 프로젝트입니다.** 공식 API가 아니라 웹 클라이언트가 쓰는 GraphQL을 그대로 호출하므로, 벨로그가 스키마를 바꾸면 깨질 수 있습니다.

<sub>An MCP server for publishing local Markdown files to velog with idempotent updates. Docs are in Korean since velog is a Korean platform.</sub>

---

## 시작하기

내려받거나 가상환경을 만들 일이 없습니다. 설정에 세 줄 넣고 로그인 한 번이면 끝입니다.

### 1. uv 설치 (한 번만)

패키지를 받아 실행해주는 도구입니다. Node의 `npx`에 해당하고, 다른 파이썬 MCP에도 그대로 씁니다.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # 또는: brew install uv
```

### 2. 클라이언트에 등록

```json
{
  "mcpServers": {
    "velog": {
      "command": "uvx",
      "args": ["--from", "velog-mcp[login]", "velog-mcp"]
    }
  }
}
```

| 클라이언트 | 설정 파일 |
| --- | --- |
| Cursor | `~/.cursor/mcp.json` |
| Claude Desktop (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` |

경로도, 토큰도, 계정명도 적지 않습니다. 어느 컴퓨터에서든 이 세 줄이 같습니다.

`[login]`은 브라우저 로그인에 필요합니다. 토큰을 직접 넣어 쓸 거라면 빼도 됩니다 — [토큰을 직접 넣기](https://github.com/mrpumpkin98/velog-mcp/blob/main/docs/reference.md#토큰을-직접-넣기)

### 3. 재시작하고 로그인

클라이언트를 완전히 종료한 뒤 다시 켭니다. MCP 서버는 시작할 때만 읽습니다. 그다음 대화에서

> 벨로그 로그인해줘

브라우저 창이 열리면 평소처럼 로그인하세요. 창이 저절로 닫히고 토큰이 저장됩니다. 벨로그는 **비밀번호 로그인이 없어서**(이메일 링크·소셜 OAuth뿐) 이 한 번만 사람이 해야 하고, 이후 만료는 서버가 알아서 갱신합니다.

확인은 이렇게 합니다. 계정명을 말할 필요가 없습니다.

> 내 벨로그 글 목록 보여줘

<details>
<summary><b>대화 대신 Connect 버튼으로 로그인하기 (선택)</b></summary>

Cursor 설정 화면의 MCP 목록에서 **Connect** 버튼을 눌러 로그인하고 싶다면 HTTP 모드로 띄웁니다. Cursor는 OAuth를 지원하는 서버에만 그 버튼을 그리고, OAuth는 stdio가 아니라 HTTP 트랜스포트에서만 동작합니다.

```bash
uvx --from "velog-mcp[login]" velog-mcp --http      # 127.0.0.1:8790
```

설정에는 `command` 대신 `url`을 적습니다.

```json
{
  "mcpServers": {
    "velog": { "url": "http://127.0.0.1:8790/mcp" }
  }
}
```

이제 Connect를 누르면 브라우저가 열려 벨로그 로그인이 진행되고, 끝나면 버튼이 Logout으로 바뀝니다. 한 번 로그인해두면 서버를 재시작해도 연결이 유지되고, 두 번째부터는 창이 뜨지 않고 즉시 연결됩니다.

**대신 이걸 감수해야 합니다.** stdio 모드는 Cursor가 서버를 알아서 띄워주지만, HTTP 모드는 **프로세스를 직접 켜둬야 합니다.** 꺼져 있으면 도구가 보이지 않습니다.

macOS라면 이 부담을 없앨 수 있습니다. 다만 자동 시작 스크립트는 저장소에 있어서, **아래 [직접 내려받아 쓰기](#직접-내려받아-쓰기)로 설치한 경우에만** 쓸 수 있습니다.

```bash
./.venv/bin/python scripts/install_launch_agent.py
```

로그인할 때 자동으로 뜨고, 어떤 이유로 죽어도 launchd가 다시 띄웁니다. 상태는 `--status`, 해제는 `--uninstall`로 봅니다. 로그는 `~/.velog-mcp/http.log`에 쌓입니다.

여기서 발급되는 OAuth 토큰은 벨로그 토큰이 아니라 **이 서버에 접근할 권한**을 뜻하는 자체 토큰입니다. 벨로그 쿠키는 예전과 같이 `~/.velog-mcp/`에만 남습니다. 서버는 루프백(`127.0.0.1`)에만 바인딩되니 **외부에 노출하지 마세요.** 남의 계정 쿠키를 대신 들고 있는 서버가 됩니다.

</details>

### 4. 글 올리기

문서 맨 위에 프런트매터를 답니다. `draft: true`가 안전장치입니다.

```markdown
---
title: 트랜잭션 경계를 다시 그은 이유
tags: [postgresql, transaction]
slug: transaction-boundary
draft: true
---

## 문제
...
```

그리고 **절대 경로**로 파일을 지정해 말합니다.

> 이 문서 벨로그에 임시저장으로 올려줘: /Users/me/docs/transaction-boundary.md

발행이 끝나면 도구가 원본 파일에 두 줄을 적어 넣습니다.

```markdown
velog_post_id: 00000000-0000-0000-0000-000000000000
velog_url: https://velog.io/@your-id/transaction-boundary
```

벨로그 웹에서 렌더링을 확인하고, 고칠 게 있으면 파일을 수정한 뒤 **같은 말을 다시 하면** 그 글이 수정됩니다. 중복 글이 쌓이지 않습니다. 만족스러우면

> 이 글 공개로 바꿔줘

---

## 도구

| 도구 | 하는 일 |
| --- | --- |
| `velog_publish_markdown_file` | **로컬 .md 발행/수정** (주로 쓰는 것) |
| `velog_login` | 로그인 창을 열어 토큰 저장 |
| `velog_whoami` | 지금 어떤 계정으로 붙는지 확인 |
| `velog_list_posts` | 글 목록 (`drafts_only`로 임시저장만) |
| `velog_get_post` | 글 하나를 본문까지 조회 |
| `velog_list_series` | 시리즈 목록·UUID |
| `velog_publish_post` | 제목·본문을 직접 넘겨 발행 |
| `velog_update_post` | `post_id`로 수정 |
| `velog_create_series` | 시리즈 생성 |
| `velog_delete_post` | 삭제 (`confirm` 필수) |

**명령어 문법은 없습니다.** 하고 싶은 일을 말하면 에이전트가 알맞은 도구를 고릅니다.

---

## 알아둘 것

- **파일 경로는 절대 경로로.** 클라이언트가 서버를 어디서 띄웠는지 알 수 없어 상대 경로는 거부합니다.
- **부분 수정은 안 됩니다.** 본문을 넘길 때는 전체를 보내야 합니다. 파일로 올리면 해당 없습니다.
- **이미지는 업로드하지 않습니다.** 본문 이미지는 이미 접근 가능한 URL이어야 합니다.
- **삭제는 되돌릴 수 없습니다.** `confirm` 없이는 실행되지 않게 막아뒀습니다.
- **첫 발행은 임시저장으로.** 코드블록·표가 의도대로 나오는지 보고 공개하세요.
- **자기 계정, 자기 글에만 쓰세요.** 대량 발행이나 자동 생성 글 양산에 쓰지 마세요. 벨로그는 개인이 운영비를 대는 서비스입니다. 호출도 사람이 글을 쓰는 속도를 넘지 않게 해주세요.

문제가 생기면 [문제 해결](https://github.com/mrpumpkin98/velog-mcp/blob/main/docs/reference.md#문제-해결)을 보세요.

---

## 직접 내려받아 쓰기

코드를 고치거나 기여할 때, 또는 `uvx` 없이 쓰고 싶을 때입니다.

```bash
git clone https://github.com/mrpumpkin98/velog-mcp.git
cd velog-mcp

python3 -m venv .venv
./.venv/bin/python -m pip install -e ".[login]"
./.venv/bin/python -m playwright install chromium   # 로그인 창용, 1회

./.venv/bin/python scripts/doctor.py                # 점검 + 등록용 JSON 출력
```

`doctor.py`가 무엇이 빠졌는지와 다음에 할 일을 알려주고, 본인 경로로 채운 설정 JSON까지 출력합니다. **막히면 이걸 먼저 실행하세요.**

이 방식으로 등록할 때는 `command`에 **가상환경 파이썬의 절대 경로**를 적습니다. 시스템 파이썬(`/usr/bin/python3`)을 적으면 패키지가 없어 서버가 뜨지 않습니다.

```json
{
  "mcpServers": {
    "velog": {
      "command": "/absolute/path/to/velog-mcp/.venv/bin/python",
      "args": ["-m", "velog_mcp"]
    }
  }
}
```

검증 스크립트 목록은 [레퍼런스](https://github.com/mrpumpkin98/velog-mcp/blob/main/docs/reference.md#스크립트)에 있습니다.

---

## 더 보기

- **[레퍼런스](https://github.com/mrpumpkin98/velog-mcp/blob/main/docs/reference.md)** — 프런트매터·환경변수 전체 목록, 검증 스크립트, 문제 해결
- **[동작 방식](https://github.com/mrpumpkin98/velog-mcp/blob/main/docs/how-it-works.md)** — 인증을 이렇게 만든 이유, 토큰 자동 갱신, 스키마를 알아낸 방법, 코드 구조

## 라이선스와 고지

이 프로젝트는 MIT 라이선스입니다 — [LICENSE](https://github.com/mrpumpkin98/velog-mcp/blob/main/LICENSE).

**벨로그와 아무 관계가 없습니다.** 벨로그 운영사의 제휴·후원·승인·지원을 받지 않은 개인 프로젝트이며, 문제가 생겨도 벨로그에 문의하지 마세요. `velog`·`벨로그`는 각 권리자의 상표이고, 이 프로젝트는 어떤 도구인지 가리키기 위해 이름을 쓸 뿐입니다. 권리자가 요청하면 이름을 바꾸겠습니다.

벨로그 본체도 MIT 오픈소스입니다([velog-io/velog](https://github.com/velog-io/velog)). 이 서버가 호출하는 쓰기 스키마도 그 저장소에 공개돼 있습니다 — [스키마를 어떻게 알아냈나](https://github.com/mrpumpkin98/velog-mcp/blob/main/docs/how-it-works.md#스키마를-어떻게-알아냈나)
