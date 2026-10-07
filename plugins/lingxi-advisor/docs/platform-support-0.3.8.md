# Lingxi Advisor 0.3.8 platform verification

Date: 2026-10-01

LingxiAdvisor core remains locked at 0.8.4. This release changes only
platform-sensitive plugin adapter and acceptance-harness behavior.

## Windows

Native Windows verification used CPython 3.12.7 with the dependencies from
`source/upstream/requirements.lock` physically installed in the test virtual
environment.

- The Pi adapter now resolves the package behind standard Windows npm
  `pi.cmd`, local `node_modules/.bin`, and POSIX/Homebrew launcher layouts.
- The OpenCode adapter derives `XDG_CONFIG_HOME` from the selected canonical
  `.../opencode` configuration root and decodes OpenCode's UTF-8 subprocess
  output explicitly. This prevents Windows ANSI-code-page mojibake from
  invalidating connected MCP status lines.
- The opt-in real-host harness resolves `node` and `npm` to concrete platform
  executables before spawning them; Python cannot launch bare `npm` on this
  Windows installation, where the executable is `npm.CMD`.
- Official Pi 0.85.1 and installed OpenCode 1.18.25 both completed attached
  and detached managed Delivery lifecycles: install, host loading, MCP tool
  verification, inspect, remove, and persistent-data preservation.
- The completed Claude Code 2.1.285 and DeepSeek Harness 0.2.0-rc.2 Windows
  wizard/lifecycle evidence from 0.3.7 remains applicable because their
  adapters and registrations did not change.

Verification commands and results:

- `.../plugin-test-venv/Scripts/python.exe -m pytest plugins/lingxi-advisor/source/tests -q -rs`:
  68 passed, 10 skipped. The skips are the two opt-in real-host cases for each
  of Chrys, OpenCode, Pi, Claude Code, and DeepSeek Harness when their
  `LINGXI_ADVISOR_REAL_*` variables are unset.
- The same interpreter with `LINGXI_ADVISOR_REAL_PI` set to the official 0.85.1
  `pi.cmd`: 2 passed (attached and detached Delivery).
- The same interpreter with `LINGXI_ADVISOR_REAL_OPENCODE` set to OpenCode
  1.18.25: 2 passed (attached and detached Delivery).
- `npx.cmd . build lingxi-advisor`: six Deliveries built and validated.
- `npx.cmd . validate lingxi-advisor`: plugin 0.3.8, six targets and six
  Deliveries valid.

No authenticated model turn or benchmark was run. Codex remains
packaging/contract verified rather than live-host accepted.

## macOS

Native macOS acceptance completed in the manually dispatched GitHub Actions
[run 36855700979](https://github.com/yiikou/CodeHelix-Plugin/actions/runs/36855700979)
at revision `0e811128837ac1d790de7b5bc8c1e9290beeb5e7`.

- Runner: macOS 15.7.9, arm64, Python 3.12.10, Node 22.23.2, npm 10.9.8,
  pnpm 10.17.1.
- Official host executables: OpenCode 1.18.25, Pi 0.85.1, Claude Code
  2.1.285, and DeepSeek Harness 0.2.0-rc.2.
- Full plugin suite: 69 passed, 10 skipped. The skips are the opt-in real-host
  cases before their environment variables are supplied.
- Normal build and validation: six Deliveries rebuilt without a working-tree
  diff; six targets and six Deliveries validated.
- Real-host lifecycle suite: 8 passed. Each official host completed attached
  and detached install, executable loading/MCP discovery, inspect, remove,
  ownership preservation, and persistent-data preservation.
- The process-level MCP suite invoked both `lingxi.advisor.search` and
  `lingxi.advisor.apply`. This proves protocol invocation without a model turn;
  it does not claim a successful knowledge retrieval or a host-routed model
  invocation.
- Every packaged LingxiAdvisor 0.8.4 wheel retained SHA-256
  `6ba0e08cbd12be9c7f36ae2d39cdd8b4b3b287a8b03af9479c1431ec38ebc05f`.

No authenticated model turn, benchmark, or interactive macOS wizard run was
performed.

## Linux

Native WSL2 acceptance is pending because this Windows system has no usable
Linux distribution: `wsl -l -v` lists only the stopped Docker Desktop internal
distribution. Completion requires installing and initializing Ubuntu 24.04
(normally `wsl --install -d Ubuntu-24.04`, with elevation/reboot if Windows
requests them), then making a separate checkout inside the Linux filesystem.
Docker Desktop was also stopped and was not used as a substitute.

Supplementary hosted-Linux acceptance completed in the same Actions run at the
same revision:

- Runner: Ubuntu 24.04.5 LTS kernel 6.17.0-1022-azure, x86_64, Python 3.12.3,
  Node 22.23.2, npm 10.9.8, pnpm 10.17.1.
- Full plugin suite: 69 passed, 10 skipped; clean six-Delivery build and
  six-target validation passed.
- The same four official hosts completed all 8 attached/detached real-host
  lifecycle cases.
- Core wheel hashes matched the macOS and Windows value above.

This hosted runner is native Linux evidence, but it does not replace the
requested WSL2 interactive-wizard acceptance.

## Acceptance levels

| Host | macOS 15 arm64 | Ubuntu 24.04 x64 | Remaining gap |
| --- | --- | --- | --- |
| Chrys / iCode | Unit/contract and Delivery validation | Unit/contract and Delivery validation | No compatible Chrys executable or interactive wizard run on these platforms |
| OpenCode 1.18.25 | Executable load/tool discovery and full managed lifecycle | Executable load/tool discovery and full managed lifecycle | Interactive wizard not run |
| Pi 0.85.1 | Executable load/tool discovery and full managed lifecycle | Executable load/tool discovery and full managed lifecycle | Interactive wizard not run |
| Codex | Packaging/contract only | Packaging/contract only | Compatible executable, live lifecycle, and wizard remain pending |
| Claude Code 2.1.285 | Executable load/tool discovery and full managed lifecycle | Executable load/tool discovery and full managed lifecycle | Interactive wizard not run |
| DeepSeek Harness 0.2.0-rc.2 | Executable load/tool discovery and full managed lifecycle | Executable load/tool discovery and full managed lifecycle | Interactive wizard not run |

The full suite directly invokes Search and Apply over MCP on both runners. The
four real-host suites verify loading and discovery, but do not route a
Search/Apply request through an authenticated model session. The completed
Windows Claude/DeepSeek interactive-wizard baseline remains unchanged.
