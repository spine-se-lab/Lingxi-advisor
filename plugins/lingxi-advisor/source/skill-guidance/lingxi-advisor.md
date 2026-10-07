## CodeHelix issue context

For an existing GitHub issue, call Search with the full public description and
the minimal identity `context={"repo":"owner/repository","issue_number":123}`.
Convert a GitHub URL to its `owner/repository` slug, omit unavailable fields
instead of sending null placeholders, and leave optional retrieval tuning at
server defaults unless the user explicitly requests otherwise. When repository
identity is unavailable, description-only Search may use authenticated GitHub
issue search to infer it. Explicit repository context always wins, and
ambiguous inference does not start live retrieval.

Bounded Search loads the public issue title and body from GitHub only when
`issue_description` is empty; a supplied description is used exactly as given.
When the user gives only a repository and issue number (or an issue URL),
either pass the real public issue text or omit `issue_description` and send
`context={"repo":"owner/repository","issue_number":123}`. Never send a
placeholder such as "investigate issue #123": it replaces the real issue text,
and retrieval and review then match on the placeholder.
