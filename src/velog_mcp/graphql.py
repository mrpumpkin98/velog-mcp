"""벨로그 GraphQL 문서 모음.

벨로그는 공식 공개 API를 제공하지 않는다. 아래 쿼리·뮤테이션은 웹 클라이언트가 쓰는
내부 엔드포인트(https://v2.velog.io/graphql)를 대상으로 하며, introspection이 차단되어
있어 인자 이름과 타입을 검증 에러 메시지로 역추적해 확정했다.

확인된 시그니처 (2026-07 기준)
    query    posts(username: String, limit: Int, cursor: ID, tag: String,
                  temp_only: Boolean): [Post]
    query    post(username: String, url_slug: String): Post
    query    user(username: String): User          # User.series_list 로 시리즈 조회
    query    auth: User                            # 미인증이면 null
    mutation writePost(title, body, tags: [String], is_markdown: Boolean,
                       is_temp: Boolean, is_private: Boolean, url_slug: String,
                       thumbnail: String, meta: JSON, series_id: ID,
                       token: String): Post
    mutation editPost(id: ID!, ...writePost와 동일 인자): Post
    mutation removePost(id: ID!): Boolean
    mutation createSeries(name: String!, url_slug: String!): Series

meta 는 반드시 객체({})로 보내야 한다
    meta 를 빼거나 null 로 보내면 벨로그는 GraphQL 에러 없이 data.writePost = null 만
    돌려준다. 로그인 상태와 무관하며, 인증 문제로 착각하기 쉽다. 웹 에디터가 보내는
    요청을 캡처해 비교한 뒤, 변수를 하나씩 바꿔가며 확인했다(2026-07 실측).
        meta 선언 없음   → null
        meta: null      → null
        meta: {}        → 성공
    token(스팸 방지용으로 보이는 인자)은 웹 에디터도 null 로 보내며, 있으나 없으나
    결과가 같았다.

스키마는 예고 없이 바뀔 수 있다. 도구가 갑자기 깨지면 이 파일을 가장 먼저 확인한다.
"""

POST_SUMMARY_FIELDS = """
  id
  title
  url_slug
  short_description
  thumbnail
  is_private
  released_at
  updated_at
  tags
"""

# 쓰기 뮤테이션 응답에는 short_description 을 요청하지 않는다.
# 벨로그의 short_description 리졸버는 뮤테이션이 돌려주는 객체에서 본문을 찾지 못해
# 터진다(errors: Cannot read properties of undefined (reading 'replace')).
# 글은 실제로 저장되는데 응답만 깨지므로, 쓰지도 않는 필드를 아예 빼는 쪽이 안전하다.
# 조회 쿼리에서는 정상 동작하므로 POST_SUMMARY_FIELDS 는 그대로 둔다. (2026-07 실측)
WRITE_RESULT_FIELDS = """
  id
  title
  url_slug
  thumbnail
  is_private
  is_temp
  released_at
  updated_at
  tags
  user {
    username
  }
"""

AUTH_QUERY = """
query VelogMcpAuth {
  auth {
    id
    username
    email
    profile {
      display_name
      thumbnail
    }
  }
}
"""

POSTS_QUERY = f"""
query VelogMcpPosts($username: String, $limit: Int, $cursor: ID, $tag: String, $temp_only: Boolean) {{
  posts(username: $username, limit: $limit, cursor: $cursor, tag: $tag, temp_only: $temp_only) {{
    {POST_SUMMARY_FIELDS}
  }}
}}
"""

POST_QUERY = f"""
query VelogMcpPost($username: String, $url_slug: String) {{
  post(username: $username, url_slug: $url_slug) {{
    {POST_SUMMARY_FIELDS}
    body
    is_markdown
    is_temp
    series {{
      id
      name
      url_slug
    }}
    user {{
      username
    }}
  }}
}}
"""

SERIES_LIST_QUERY = """
query VelogMcpSeriesList($username: String) {
  user(username: $username) {
    id
    username
    series_list {
      id
      name
      url_slug
      posts_count
    }
  }
}
"""

WRITE_POST_MUTATION = f"""
mutation VelogMcpWritePost(
  $title: String
  $body: String
  $tags: [String]
  $is_markdown: Boolean
  $is_temp: Boolean
  $is_private: Boolean
  $url_slug: String
  $thumbnail: String
  $series_id: ID
  $meta: JSON
) {{
  writePost(
    title: $title
    body: $body
    tags: $tags
    is_markdown: $is_markdown
    is_temp: $is_temp
    is_private: $is_private
    url_slug: $url_slug
    thumbnail: $thumbnail
    series_id: $series_id
    meta: $meta
  ) {{
    {WRITE_RESULT_FIELDS}
  }}
}}
"""

EDIT_POST_MUTATION = f"""
mutation VelogMcpEditPost(
  $id: ID!
  $title: String
  $body: String
  $tags: [String]
  $is_markdown: Boolean
  $is_temp: Boolean
  $is_private: Boolean
  $url_slug: String
  $thumbnail: String
  $series_id: ID
  $meta: JSON
) {{
  editPost(
    id: $id
    title: $title
    body: $body
    tags: $tags
    is_markdown: $is_markdown
    is_temp: $is_temp
    is_private: $is_private
    url_slug: $url_slug
    thumbnail: $thumbnail
    series_id: $series_id
    meta: $meta
  ) {{
    {WRITE_RESULT_FIELDS}
  }}
}}
"""

REMOVE_POST_MUTATION = """
mutation VelogMcpRemovePost($id: ID!) {
  removePost(id: $id)
}
"""

CREATE_SERIES_MUTATION = """
mutation VelogMcpCreateSeries($name: String!, $url_slug: String!) {
  createSeries(name: $name, url_slug: $url_slug) {
    id
    name
    url_slug
  }
}
"""
