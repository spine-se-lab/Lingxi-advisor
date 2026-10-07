# Lingxi Advisor 验收记录

当前问题、2026-10-04 实测及 main 整合状态见[本轮联合验收记录](../../../docs/acceptance/lingxi-advisor-swe-pro/2026-10-04/issues/README.md)。以下记录保留其原日期与验证范围。

## 2026-10-07 Chrys / iCode 0.28 普通模式真实验收

- 宿主：官方 `openJiuwen-ai/iCode` tag `v0.28.0`，commit
  `5344293d0dc95a42d2883c9470b901ae0d48c553`；使用隔离的 checkout、`APPDATA`、
  CodeHelix home 与 Lingxi Advisor data root。
- 插件：Lingxi Advisor `0.3.13`；六个 Delivery 重新构建、校验通过，插件测试
  `143 passed, 10 skipped`。Windows CRLF checkout 测试在隔离 Git 仓库显式开启
  `core.longpaths`，不修改用户全局 Git 配置。
- 凭据：从仓库外 `Lingxi-TaskPatternGuidance/.env` 注入 GitHub 与模型环境变量；
  Chrys model profile 只保存 `{{TASKPATTERN_JUDGE_API_KEY}}` 引用，未把密钥写入
  profile、命令参数或本记录。
- 安装：真实执行 managed install/verify；Chrys 加载 `LingxiAdvisor` Agent Profile、
  两个 Skill、Runtime Search/Apply 两个工具和 Operator 六个工具，两个 MCP server
  均连接成功。
- 普通模式案例：用 `icode run --agent LingxiAdvisor --model lingxi-acceptance`
  处理公开 `pytest-dev/pytest#15132` issue description；工作目录为空并明确禁止改码。
  Search 使用 `prepare_if_missing=true` 完成真实 GitHub retrieval、Gate 与 Artifact
  generation，选中 3 个候选、拒绝 2 个，生成以下 refs：
  - `light/pytest-dev__pytest__issue_14953`
  - `light/pytest-dev__pytest__issue_14675`
  - `light/pytest-dev__pytest__issue_14638`
- Agent 对三个 ref 均成功调用 Apply，并在最终回答中用 Apply 内容形成
  “扩展 `addini` 数值类型、读取时统一转换、区分 unset 与 0、保留 TOML 原生类型”
  的定位和测试建议；不是只完成 tools/list 或 Search 调用。会话 id
  `733eaa45-f8bd-4924-b223-38b446309042`，端到端耗时 `766.521s`。
- 本轮只验收一个 issue 的首次普通模式闭环；第二次缓存复用与 fail-open 未重跑，
  不在本次通过范围内。

本文保留 2026-09-11 的历史记录。后续 0.3.0 / core 0.8.0 的实现与逐项实测见 [实施记录](implementation-progress.md)，下文限制不代表当前机器或当前版本状态。

## 本次 0.2.0 已验证

- 锁定的来源仓 commit 与当前 `Lingxi-LingxiAdvisorGuidance` HEAD 均为
  `83ec6841e3e80026c353c7abb06515c5598ce700`；
- release closed-world 校验同时要求完整 wheel、Runtime/Operator descriptor 和两个 Skill；
- iCode / Chrys Profile 同时绑定 Runtime 与 Knowledge Preparation Operator 两套 Skill/MCP；
- OpenCode JSONC 保留未知字段，并同时注册 `mcp.lingxi-advisor` 与
  `mcp.lingxi-advisor-operator`；
- GitHub token 支持逗号/分号输入与 `GITHUB_TOKEN_1...15`，去重后仍沿用上游 rotation；
- 未提供模型时不写 Judge/Generator 环境变量，Runtime 使用 MCP Host sampling；提供可选
  `gate_model_base_url`、`gate_model_name` 和模型 key 时映射到独立模型；
- repository 不再是安装配置，安装后的 Skill 从当前结构化任务上下文取得 repo、instance id、
  base commit 和公开问题描述；
- `allow_preretrieved_updates` 默认开启，安装后的 Runtime/Operator Skill 将首次准备调用的
  `update_preretrieved` 默认为 `true`；
- `npx . build lingxi-advisor` 和 `npx . validate lingxi-advisor` 通过；
- 插件聚焦测试：`20 passed, 4 skipped`。skip 均为需要外部真实 Chrys/OpenCode/凭据的验收。

## 历史真实验收（0.1.x）

旧版曾在 Chrys `0.20.1` 与 OpenCode `1.18.25` 完成四阶段安装，并用公开 Django issue
跑通 `lingxi.advisor.search -> lingxi.advisor.apply`。这些证据证明上游 runtime 基线，不代表
0.2.0 新增的 Operator 注册和免模型安装已经在真实宿主复测。

## 尚未宣称通过

- 本机没有 `chrys` 命令，也没有 `~/.chrys` 配置目录，因此本次不能伪称真实 Chrys
  Profile 已在本机加载；
- 0.2.0 在真实 Chrys 会话中的 Host sampling、首次生成、缓存复用和 fail-open；
- 0.2.0 Operator 的真实 GitHub + Judge/Generator 长任务；
- OpenCode 当前不支持 MCP sampling；未配置独立模型时只保证安装、缓存读取和不触发 LLM 的路径；
- macOS/Linux 的 installer 与真实 POSIX 子进程树验收。

真实凭据只应通过安装提示或环境变量传入，不写入证据文件。
