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
  ) {{
    {POST_SUMMARY_FIELDS}
    is_temp
    user {{
      username
    }}
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
  ) {{
    {POST_SUMMARY_FIELDS}
    is_temp
    user {{
      username
    }}
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
