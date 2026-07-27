# 동작 방식

← [README](../README.md)

왜 이렇게 만들었는지, 그리고 어디가 깨질 수 있는지에 대한 기록.

## 왜 아이디·비밀번호를 안 받나

**벨로그에는 비밀번호 로그인이 없습니다.** GraphQL에는 `logout`만 있고 로그인 뮤테이션이 없으며, REST 쪽에도 비밀번호를 받는 엔드포인트가 없습니다(`/api/v2/auth/login` → 404). 열려 있는 것은 이 둘뿐입니다.

| 엔드포인트 | 동작 |
| --- | --- |
| `POST /api/v2/auth/sendmail` | `{"email":"..."}` → 로그인 링크 메일 발송 |
| `GET /api/v2/auth/code/:code` | 메일 속 코드를 토큰으로 교환 |

즉 로그인 수단은 **이메일 매직링크 또는 소셜 OAuth**뿐입니다. 그래서 자격증명을 저장하는 대신, 브라우저에서 한 번 로그인해 쿠키를 받아두고 그 뒤로는 토큰만 관리하는 방식을 택했습니다.

## 토큰이 관리되는 방식

인증은 `access_token`·`refresh_token` 쿠키로 합니다. `access_token`이 만료되면 벨로그가 `refresh_token`을 보고 새 토큰을 `Set-Cookie`로 내려주는데, 이 서버는 응답 헤더에서 그것을 붙잡아 저장소에 반영합니다. 그래서 평소에는 아무것도 하지 않아도 갱신됩니다.

| 상황 | 해야 할 일 |
| --- | --- |
| 처음 설치 | `velog_login` 한 번 (브라우저에서 인증) |
| `access_token` 만료 | 없음 — 자동 갱신 |
| `refresh_token` 만료 | `velog_login` 다시 (`headless=True`면 창도 안 뜸) |

토큰은 `~/.velog-mcp/tokens.json`에 `0600` 권한으로, 임시 파일에 쓴 뒤 교체하는 방식으로 저장합니다. 브라우저 프로필은 `~/.velog-mcp/browser`에 남으므로 두 번째 로그인부터는 사람이 손댈 일이 없습니다.

**단, `Set-Cookie` 회전은 실서버에서 아직 확인되지 않았습니다.** 회전 처리 로직은 로컬 가짜 서버로 5가지 시나리오를 검증했지만(`scripts/verify_token_rotation.py`), 벨로그가 실제로 어떤 조건에서 새 토큰을 내려주는지는 유효한 토큰으로 만료를 겪어봐야 알 수 있습니다. 갱신이 안 되는 것 같으면 `velog_whoami`의 `token_source`를 보고 `scripts/login.py --headless`로 갱신하세요.

## 스키마를 어떻게 알아냈나

벨로그의 GraphQL은 **introspection이 막혀 있습니다.** 스키마를 물어보면 `GRAPHQL_VALIDATION_FAILED`가 돌아옵니다. 그래서 일부러 틀린 타입·이름으로 요청을 보내고 검증 에러 메시지를 읽어(예: `Expected type String, found 1.`) 인자 이름과 타입을 하나씩 역추적해 확정했습니다. 그 근거는 `src/velog_mcp/graphql.py` 상단 주석에 남겨두었습니다.

따라서 **벨로그가 스키마를 바꾸면 도구가 깨집니다.** 그때 가장 먼저 볼 파일도 거기입니다.

또 하나 알아둘 함정은, 벨로그가 **미인증 상태에서 `writePost`를 호출해도 GraphQL 에러 없이 `null`만 돌려준다**는 점입니다. 그대로 두면 "발행 성공"으로 보이므로, 이 서버는 쓰기 결과가 비어 있으면 인증 오류로 바꿔서 알려줍니다.

## 코드 구조

```
src/velog_mcp/
  server.py        도구 10개 정의 — 입력 검증·가드·응답 정리
  client.py        GraphQL 호출, 쿠키 인증, Set-Cookie 회전 흡수, 에러 변환
  graphql.py       쿼리·뮤테이션 문서 (+ 실측한 스키마 기록)
  markdown.py      프런트매터 파싱, H1 제목 승격, 발행 후 id 기록
  browser_login.py 브라우저 로그인 (MCP 도구·CLI가 함께 사용)
  token_store.py   토큰 파일 원자적 쓰기 (0600)
  config.py        환경변수 + 저장소 병합
scripts/
  doctor.py        설치 점검 + 다음 할 일 안내
  login.py         터미널에서 브라우저 로그인
  smoke_test.py    MCP 프로토콜로 조회 도구 검증
  dry_run_markdown.py      마크다운 발행 로직 검증
  verify_token_rotation.py 토큰 자동 갱신 검증
  verify_mcp_config.py     클라이언트 설정으로 연결 검증
```

## 기여

이슈·PR 환영합니다.

- 벨로그 스키마 변경으로 깨진 경우: 실패한 도구 이름과 에러 메시지를 함께 적어주세요.
- 새 필드·인자를 추가하는 경우: **어떻게 확인했는지**를 남겨주세요. 스키마가 역추적으로 알아낸 것이라 근거가 다음 사람에게 그대로 자산이 됩니다.

검증 스크립트는 글을 만들지 않습니다. 실제 발행을 시험할 때는 `draft=True` 또는 `VELOG_DRY_RUN=true`를 쓰세요.
