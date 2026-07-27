# velog-mcp

> 에이전트에게 **"이 문서 벨로그에 올려줘"** 라고 말하면 되는 MCP 서버

로컬 마크다운 파일을 [벨로그](https://velog.io)에 발행합니다. 발행하면 파일에 글 id가 적히고, **같은 파일을 다시 올리면 새 글이 생기는 대신 그 글이 수정됩니다.** Cursor·Claude Desktop 등 MCP 클라이언트에 그대로 붙습니다.

> ⚠️ 벨로그 공식 API가 아닙니다. 웹 클라이언트가 쓰는 내부 GraphQL을 호출하므로 벨로그가 스키마를 바꾸면 깨질 수 있습니다.

<sub>An MCP server for publishing local Markdown files to velog with idempotent updates. Docs are in Korean since velog is a Korean platform.</sub>

---

## 시작하기

### 1. 설치

```bash
git clone https://github.com/mrpumpkin98/velog-mcp.git
cd velog-mcp

python3 -m venv .venv
./.venv/bin/python -m pip install -e ".[login]"
./.venv/bin/python -m playwright install chromium   # 로그인 창용, 1회

./.venv/bin/python scripts/doctor.py                # 점검 + 등록용 JSON 출력
```

`doctor.py`가 지금 무엇이 빠졌는지와 다음에 할 일을 알려줍니다. **막히면 항상 이걸 먼저 실행하세요.**

### 2. 클라이언트에 등록

`doctor.py`가 **본인 경로로 채워서** 출력한 JSON을 설정 파일에 붙여넣습니다.

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

| 클라이언트 | 설정 파일 |
| --- | --- |
| Cursor | `~/.cursor/mcp.json` |
| Claude Desktop (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` |

토큰도 계정명도 적지 않습니다. `command`는 반드시 **가상환경 파이썬의 절대 경로**여야 합니다. 시스템 파이썬(`/usr/bin/python3`)을 적으면 패키지가 없어 서버가 뜨지 않습니다.

### 3. 재시작하고 로그인

클라이언트를 완전히 종료한 뒤 다시 켭니다. MCP 서버는 시작할 때만 읽습니다. 그다음 대화에서

> 벨로그 로그인해줘

브라우저 창이 열리면 평소처럼 로그인하세요. 창이 저절로 닫히고 토큰이 저장됩니다. 벨로그는 **비밀번호 로그인이 없어서**(이메일 링크·소셜 OAuth뿐) 이 한 번만 사람이 해야 하고, 이후 만료는 서버가 알아서 갱신합니다.

확인은 이렇게 합니다. 계정명을 말할 필요가 없습니다.

> 내 벨로그 글 목록 보여줘

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

문제가 생기면 `scripts/doctor.py` → [문제 해결](docs/reference.md#문제-해결) 순서로 보세요.

---

## 더 보기

- **[레퍼런스](docs/reference.md)** — 프런트매터·환경변수 전체 목록, 검증 스크립트, 문제 해결
- **[동작 방식](docs/how-it-works.md)** — 인증을 이렇게 만든 이유, 토큰 자동 갱신, 스키마를 알아낸 방법, 코드 구조

## 라이선스

MIT — [LICENSE](LICENSE). 이 프로젝트는 벨로그와 아무 관계가 없으며 공식 지원을 받지 않습니다.
