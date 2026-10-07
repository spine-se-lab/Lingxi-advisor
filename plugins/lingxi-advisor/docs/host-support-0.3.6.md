# Lingxi Advisor 0.3.6 host acceptance

Date: 2026-09-30

LingxiAdvisor core remained locked at 0.8.4. Both new targets package only the
`lingxi-advisor` Skill and the Runtime MCP surface (`lingxi.advisor.search` and
`lingxi.advisor.apply`); neither target packages the Operator.

## Claude Code 2.1.285

- Executable identity: official `@anthropic-ai/claude-code@2.1.285` package,
  reporting `2.1.285 (Claude Code)`.
- The normal repository CLI selected the `claude-code-2.1.285` Delivery through
  `--agent claude-code`, installed the standalone Skill into the isolated
  `CLAUDE_CONFIG_DIR`, and managed only `mcpServers.lingxi-advisor` in the
  project's `.mcp.json`.
- `claude plugin validate --strict` accepted the packaged Skill validation
  manifest. `claude mcp get lingxi-advisor` loaded the project registration and
  reported the expected command, arguments, and environment references. A
  fresh isolated project reports project MCP servers as pending interactive
  approval until `claude` is opened there; no authenticated model turn was
  used for this acceptance.
- The managed Runtime completed MCP initialize and tools/list with exactly
  `lingxi.advisor.search` and `lingxi.advisor.apply`.
- CodeHelix inspect reported `loaded: true`. Removal deleted the LingxiAdvisor
  registration while preserving an unrelated project MCP server and a marker
  under the persistent LingxiAdvisor data root.

## DeepSeek Harness 0.2.0-rc.2

- Executable identity: official `@deepseek-ai/dsh@0.2.0-rc.2` package,
  reporting `0.2.0-rc.2`; `pnpm` was available for the official profile plugin
  lifecycle.
- The normal repository CLI selected the `deepseek-harness-0.2.0-rc.2`
  Delivery through `--agent deepseek-harness`, installed the standalone Skill
  into an isolated `DSH_HOME`, and installed the generated bundle with
  `dsh plugin --profile web add`.
- `dsh --profile web --dump-config` composed the
  `codehelix-lingxi-advisor-mcp` entry using the official
  `@deepseek-ai/dsh-mcp-client`.
- A real `dsh web` run started the LingxiAdvisor managed launcher, issued an MCP
  `ListToolsRequest`, and reached the web-ready state. The process was then
  stopped; no authenticated model turn was used.
- CodeHelix inspect reported `loaded: true`. Removal used
  `dsh plugin --profile web remove`, retained the built-in
  `@deepseek-ai/dsh-base` and `@deepseek-ai/dsh-web-app` bundles, and preserved
  a marker under the persistent LingxiAdvisor data root.

Pi 0.85.1 and Codex 0.136.x remain packaging/contract verified only; this
acceptance does not claim a live-host result for them.
