# Lingxi Advisor

Lingxi Advisor 为 Coding Agent 提供历史问题知识检索、应用和知识准备能力。插件版本为 `0.3.13`，核心为 LingxiAdvisor `0.8.6`。Chrys/iCode、OpenCode、Pi、Codex、Claude Code 与 DeepSeek Harness 六个 Target 都从同一份锁定上游 wheel 构建；没有宿主专属的 LingxiAdvisor 业务分支。

Chrys/iCode 与 OpenCode 安装两个固定 Skill 和两个 stdio MCP；Pi、Codex、Claude Code 与 DeepSeek Harness 只接入 Runtime Search/Apply 和 `lingxi-advisor` Skill，Operator 接入保持在原有两个宿主：

| 使用入口 | 能力 |
| --- | --- |
| `lingxi-advisor` Skill / Runtime MCP | `lingxi.advisor.search`、`lingxi.advisor.apply` |
| `knowledge-preparation-operator` Skill / Operator MCP | 能力查询、单任务准备、异步批任务、状态与结果查询、知识读取 |

仓库和问题身份由调用时的公开任务上下文提供，不是安装配置。检索保留同仓库、时间边界、安全过滤和 LLM Gate；生成支持 Light 与 Grounded Analysis，制品保留来源与内容摘要。

Chrys 当前仅交付 `icode-chrys-0.28`，目标为 0.28.0；旧版支持声明已移除。安装、配置及尚未完成的在线知识链路见[当前验收记录](../../docs/acceptance/lingxi-advisor-swe-pro/2026-10-04/issues/README.md)。

| Target | 宿主接入 | 本轮验证 |
| --- | --- | --- |
| Chrys / iCode | managed Profile、Skill、Runtime/Operator MCP | 既有真实宿主记录与回归测试 |
| OpenCode | managed Skill 与两个 MCP JSONC 字段 | 既有真实宿主记录与回归测试 |
| Pi 0.85.1 | managed `skills/lingxi-advisor` 与单一 owned Extension；Extension 将 provider-safe alias 接到 Runtime MCP | fixture loader、安装/验证/所有权回归；真实验收可用 `LINGXI_ADVISOR_REAL_PI` 开启 |
| Codex 0.136.x | 共享 `codex/native-plugins` adapter、原生 Skill 与 MCP manifest | native package/adapter contract、锁定核心逐文件一致性；未将本机 0.154 alpha 冒充受支持版本 |
| Claude Code 2.1.285 | managed standalone Skill 与项目 `.mcp.json` 的 `mcpServers.lingxi-advisor` 字段 | 官方 CLI 严格校验、项目注册、Runtime MCP、install/inspect/remove 实跑；新项目注册仍需 Claude 交互批准 |
| DeepSeek Harness 0.2.0-rc.2 | managed filesystem Skill 与官方 `web` profile bundle / `dsh-mcp-client` | 官方 `dsh` 安装、组合、真实 `dsh web` 加载、MCP tools/list、inspect/remove 实跑 |

## 安装与凭据

完整仓库 CLI、独立 Delivery CLI、Product Plugin Management 都调用共享 Kit 的 prepare/commit/inspect/remove 生命周期。安装保存非敏感配置；GitHub 和模型密钥由启动 Agent/MCP 的进程环境提供，**不会写入 runtime.env**。Codex 原生 Runtime 还会从所选 LingxiAdvisor data directory 的 `.env` 补齐未由宿主注入的 GitHub token；启动环境中的值优先。

### HTML 配置页面

安装完成后，可从仓库启动本地配置页面；它读取并更新 Runtime 已使用的 managed binding，不创建第二份配置：

```sh
npx ./plugins/lingxi-advisor config-ui --home /absolute/path/to/codehelix-home
```

存在多个有效部署时，追加 `--deployment-id <id>`。独立 Delivery 可用 `npx --yes --package /absolute/path/to/delivery codehelix-lingxi-advisor config-ui --home /absolute/path/to/codehelix-home` 启动。服务默认只监听 `127.0.0.1`，页面可编辑 Delivery 已声明的模型名称与端点、Judge 输出额度、Operator batch 输入路径及既有 retrieval policy flags；`data_root`、issue provider 和 Codex `workbench_workspace` 属于安装接线，页面只读，需通过正常安装流程更改。

凭据仍由启动环境中的 `GITHUB_TOKEN`（及轮换变量）和 `LINGXI_ADVISOR_MODEL_API_KEY` 提供。页面只显示 present/missing，不读取或返回凭据值。保存前会复用现有配置校验并安全替换 binding，同时同步 PluginState 的 binding digest；保存后需重启或 reload 对应 Agent/MCP Runtime。

Claude Code 与 DeepSeek Harness 目前复用共享 CLI 的显式目标选择路径；共享 Kit 尚未提供这两个宿主的自动发现器，因此安装时应同时给出 `--agent`、`--target` 与 `--config-root`。这不是新的向导或旁路安装流程。

需要实时 GitHub 检索时，在启动环境设置 `GITHUB_TOKEN`，可再使用 `GITHUB_TOKEN_1` 至 `GITHUB_TOKEN_15`。多个 token 经规范化和去重后交给核心轮换。更新凭据后重启 Agent/MCP 即可，不需要重装。

自定义模型同时配置 `gate_model_name`、`gate_model_base_url`，启动环境设置 `LINGXI_ADVISOR_MODEL_API_KEY`；也可分别使用 `LINGXI_ADVISOR_JUDGE_API_KEY` 和 `LINGXI_ADVISOR_GENERATOR_API_KEY`。例如使用 Chrys DeepSeek V4 Flash profile 对应的公开配置：

```sh
npx . lingxi-advisor install --agent icode \
  --target /absolute/path/to/chrys --config-root /absolute/path/to/chrys-config \
  --set gate_model_name=deepseek/deepseek-v4-flash-0731 \
  --set gate_model_base_url=https://openrouter.ai/api/v1
```

命令执行前，应在环境中提供实际密钥；不要把密钥放进 `--set`、命令行或配置文件。插件不自动读取或修改 Chrys model profile，验收脚本按 Chrys 的环境模板规则解析该 profile。

Judge 输出额度默认 `32768`，可用 `--set judge_max_output_tokens=<n>` 调整（1024–131072）。0.3.13 起默认值由 `16384` 提高：DeepSeek V4.1 Flash 等推理模型在 16384 下可能耗尽额度。该额度在支持推理的服务上可能同时包含推理和最终正文；耗尽额度会报告模型输出截断，不会把不完整判断当成有效结果。

不配置自定义模型时，Runtime 在支持 MCP sampling 的宿主中使用宿主模型。Operator 当前没有宿主 sampling 路径，需要生成时应配置自定义模型。

OpenCode `1.18.34` 与 Claude Code `2.1.285` 的 MCP 客户端在 initialize 中不声明 sampling 能力，因此这两个 Target 从 0.3.13 起**必须**配置自定义模型：安装预检和配置页面会拒绝缺少 `gate_model_name` / `gate_model_base_url` 的配置。模型密钥仍只从启动环境的 `LINGXI_ADVISOR_MODEL_API_KEY` 读取。OpenCode 安装时若能从 `opencode.json(c)` 识别当前宿主模型（OpenRouter、OpenAI、DeepSeek 或带 `baseURL` 的自定义 provider），报错会给出对应的 `--set` 建议；只读取模型名和端点，不读取宿主凭据。

OpenCode 对 MCP 工具调用默认 60 秒超时，而带知识生成的 Search 通常需要数分钟。OpenCode Target 把 `mcp_request_timeout_seconds`（默认 `900`，30–1800）写入两个 MCP 字段的 `timeout`，无需修改全局 `experimental.mcp_timeout`。

Claude Code 将项目 `.mcp.json` 的服务器保持为待批准状态：安装后需在项目目录交互运行一次 `claude`，信任项目并启用 `lingxi-advisor`，之后 `claude -p` 才会加载它；安装结果会给出这一步提示。

独立 Delivery 可复制到仓库外执行：

```sh
npx --yes --package /absolute/path/to/delivery codehelix-lingxi-advisor install --agent opencode \
  --target /absolute/path/to/project --config-root /absolute/path/to/agent-config
```

`--home` 指定 CodeHelix home，`--method copy` 或 `--method symlink` 选择 Skill 投影方式。安装器展示计划后确认；自动化可使用 `--yes`。源码来源移走后，已安装的代码和管理入口从保留的 PackageStore 与 Kit 运行。

## 安装后的责任与落点

| 对象 | 所有者与用途 |
| --- | --- |
| PackageStore | Kit 保存完整、按摘要锁定的执行包；不是临时源码备份 |
| 一个 Python Runtime | Kit 按锁定依赖构建，Runtime/Operator 共用 |
| Config binding | Kit 保存非敏感配置和部署引用 |
| Skill | Kit 或宿主原生插件机制投影到对应 Skill 目录并记录所有权；Pi/Codex/Claude Code/DeepSeek Harness 只投影 Runtime Skill |
| 宿主接线 | Chrys Profile、OpenCode MCP 字段、Pi owned Extension、共享 Codex native adapter、Claude 项目 MCP 字段，或 DeepSeek `web` profile bundle |
| DataRef | 指向实际 knowledge、batch、run、cache 和 preretrieved 目录；移除不删除这些数据 |

Chrys 从目标 checkout 的 `Code.yaml` 派生 `LingxiAdvisor.yaml`。OpenCode 注册 `mcp.lingxi-advisor` 和 `mcp.lingxi-advisor-operator`，只管理这两个 JSONC 字段，保留无关字段及注释。Pi 在宿主 `extensions/` 中只写入 `codehelix-lingxi.advisor.js`，并把 `lingxi-advisor_search` / `lingxi-advisor_apply` 映射到同名 canonical MCP 工具。Codex Delivery 由共享 native adapter 生成 `.codex-plugin/plugin.json`、`.mcp.json` 与本地 marketplace。Claude Code 只管理项目 `.mcp.json` 的 `mcpServers.lingxi-advisor`；DeepSeek Harness 通过官方 `dsh plugin --profile web` 生命周期管理一个本地 bundle。安装、inspect 和 remove 均使用共享宿主生命周期。所有目标都通过绝对路径引用已安装 Package 与 Runtime。

默认数据根为 `<config_root>/lingxi/advisor/data`，可用 `--set data_root=/absolute/path` 覆盖。Operator 批任务从安装配置 `batch_input_path` 指定的公开任务 JSONL 读取。`allow_live_search`、`allow_preretrieved_updates` 默认开启；`allow_refresh`、`allow_clone`、`allow_fetch` 默认关闭，需要 Grounded 检出仓库时按需求显式启用。

稳定 export 保留在 `<config_root>/lingxi/advisor/exports/lingxi.advisor.runtime-v1.json`，仍只声明一个 Runtime Skill、一个 Runtime MCP 和两个工具；Operator 独立注册。

## 核心结构与构建

核心在上游实现一次后导入，插件 Source 不再维护另一套业务实现。

| 核心边界 | 0.8.6 的职责 |
| --- | --- |
| composition / resolved settings | 一次性解析配置并组装共享能力 |
| generation service | 内存候选经缓存检查或生成产出 Artifact；CLI 负责 JSONL 输入适配 |
| GitHub transport / query / discovery | HTTP 与 token、查询构造、历史修复规则分开；旧 CLI 是边缘适配 |
| Artifact validation | XML 结构、来源内容摘要和读取校验共用规则 |
| Run / Batch state | 明确状态，按 result → manifest → 派生索引提交；索引可重建 |
| execution / policy | 核心执行权限、错误分类、请求时间预算、协作取消 |

取消不能强杀正在执行的同步 HTTP；当前请求依赖 I/O timeout 返回，之后检查取消状态并禁止后续重试或发布。

```sh
python plugins/lingxi-advisor/scripts/import-lingxi-advisor-release.py --source-root /absolute/path/to/lingxi-advisor
npx . build lingxi-advisor
npx . validate lingxi-advisor
```

导入要求干净、已提交的上游快照，通过完整测试并两次构建得到相同归档。日常构建只消费锁定的 `source/upstream` 归档。Codex host wheel 的构建后端从该归档提取原 core 文件并只添加宿主入口；测试逐文件核对 `lingxi-advisor/` 内容。安装合同见 [custom installer protocol](../../docs/specifications/custom-installer-protocol.md)，范围与当前证据见 [实施记录](docs/implementation-progress.md)，历史验收见 [acceptance.md](docs/acceptance.md)，新宿主实跑见 [0.3.6 host acceptance](docs/host-support-0.3.6.md)，平台适配见 [0.3.8 platform verification](docs/platform-support-0.3.8.md)。历史版本曾实际加载 Chrys 0.18.1、0.20.1、0.25.1、OpenCode 1.18.25、Pi 0.85.1、Claude Code 2.1.285 与 DeepSeek Harness 0.2.0-rc.2；Codex 仍为 fixture/contract 验证，未声称未经执行的真实宿主验收。0.20.1 验收使用本机有既存修改的 checkout；未改动其源码。
