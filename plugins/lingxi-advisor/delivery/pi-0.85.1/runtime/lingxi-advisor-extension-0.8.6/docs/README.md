# LingxiAdvisor — V4 使用与集成手册

LingxiAdvisor 从同仓库历史 Issue/Patch 生成可复用 XML Artifact，并在当前
Coding Agent 任务中搜索和应用这些知识。V4 只有一套 `lingxi_advisor` Core
Package，但提供两个彼此独立的 Delivery Profile：

- Runtime Profile：普通 Coding Agent，只暴露 `lingxi.advisor.search` 与
  `lingxi.advisor.apply`。
- Operator Profile：知识准备与运维流程，只暴露 Codify Operation 工具。

Retrieval、Safety、Gate、Light/Grounded Generation、XML schema 和 Artifact
Store 由两个 Profile 共用，不复制算法或 wheel。

## 1. 能力与交付边界

Core 能力归属：

- Codify：显式 prepare、Search 按需 ensure、Batch Preparation、任务结果和 XML 查看。
- Activate：Search 与 Apply。
- Artifact Store：Artifact lookup、read 与 store。

Skill 是无状态工作流说明，Agent Profile 是 Host 配置，MCP Server 执行能力，
server descriptor 告诉 Host 如何启动 Server。外部 Host 不构造内部对象。

## 2. Runtime Profile

Runtime Skill 位于 skills/lingxi_advisor/，Agent Profile 位于其 agents/openai.yaml，
descriptor 位于 packaging/runtime-server.json。

标准流程：

    具体不确定性
    → lingxi.advisor.search
    → 选择相关 Knowledge Matches
    → lingxi.advisor.apply
    → 使用 content，并保留 source_artifact_refs

最小 Search 调用只有一个必填字段：

    lingxi.advisor.search(issue_description)

这个最小调用只匹配已有且已审核的本地预检索知识。SWE-bench 风格任务继续使用
公开的 `repo + instance_id + base_commit` 进入 live 同仓库检索。普通 GitHub
issue 没有 instance id 或 base commit 时，只需提供公开的 `repo + issue_number`；
Server 会补全稳定 identity、issue 创建时间和基线 commit，再运行相同 workflow。
尚未登记的新 issue 只需提供 `repo + issue_description`；Server 会自动识别为新 issue，
派生 path-free identity、解析请求开始前的最新 commit，并以请求时间建立有界
live-search boundary。
四个字段都只是可选 context，MCP schema 不要求 null 占位。

Search 继续支持 context、Retrieval/Gate 高级参数和 generation_mode：

- 显式 `target_issue`、`instance_id`、legacy `issue_id` 或正数 `issue_number`
  自动识别为 existing target；没有 target identity 时自动识别为 new issue；
- 有 repository 的新 issue 执行有界历史检索；没有 repository 时不会猜测或提示；
- Search 自动复用有效兼容的 Artifact；缺失、失效或不兼容时通过现有
  Codify.ensure 路径准备或重新生成；
- existing target 默认启用 target-specific leakage check；调用方可显式关闭，
  但同仓库、时间边界、Patch 和通用检索验证始终保留；
- generation_mode=light：快速生成；
- generation_mode=grounded_analysis：需要代码证据的较重生成。

Generation 始终 cache-first。缓存命中直接复用已验证 Artifact，不重复模型调用，
也不重新创建 Grounded worktree。缓存缺失时，Light 不读取 repository worktree，
以历史 Issue/Patch 为 target-independent 输入执行 FG1、FG2、General 并校验最终
XML；Grounded 则在 Server 准备的 detached post-fix worktree 中读取代码，校验
HEAD、仓库根目录、clean 状态、路径/祖先关系/patch-id 一致性，并在结束时再次
验证 worktree 未被修改。Grounded 的只读 Git 命令有界执行，不在分析阶段隐式
fetch；Summarizer 不使用工具。

Search 直接返回 knowledge_matches[].knowledge_xml，不需要 Runtime get/view
工具。Portable Apply 固定为：

    lingxi.advisor.apply(
      issue_description,
      knowledge_matches
    )

Portable 返回只依赖 status、content、source_artifact_refs 和 error。

Python 高级接口仍可提供 context、artifact_refs、sections 和 max_content_chars
等选择参数，但这些不是 Runtime Skill、MCP schema 或 Host descriptor 的依赖。
内部 Assembly、chunk/index 与诊断字段也不构成 portable contract。

## 3. Operator Profile

Operator Skill 位于 skills/knowledge-preparation-operator/，产品名称为 Knowledge
Preparation Operator；descriptor 位于 packaging/operator-server.json。

Operator 只暴露：

    knowledge_preparation_capabilities
    prepare_historical_knowledge
    start_preparation_batch
    get_preparation_batch
    get_preparation_result
    read_prepared_knowledge

Operator 不是 Runtime 超集。需要两组工具时，Host 应同时挂载两个 Profile。

单任务流程：

    prepare_historical_knowledge
    → get_preparation_result（恢复或复查）
    → read_prepared_knowledge

批量流程：

    start_preparation_batch
    → get_preparation_batch（轮询 running 与终态）
    → get_preparation_result
    → read_prepared_knowledge

Batch Preparation 属于 Codify。LingxiAdvisorCodifyBatch 复用同一个单任务 Codify
Operation；capability 通过 BatchInputSource port 获取批量实例。
adapters/batch/input_source.py 负责读取和校验 Host 授权的 JSONL，job_store.py 与
worker.py 分别只负责文件状态/锁/恢复和后台执行。generation_mode 仍只有 light 和
grounded_analysis。

Batch 输入不是 Agent 工具参数，而是 Operator Host 管理的授权 JSONL。每行是一条
公开任务实例，至少包含：

    {"instance_id":"task-1","repo":"owner/repo","base_commit":"<sha>","problem_statement":"<issue>"}

启动 Batch 前，Host 必须使用以下任一方式配置文件：

    lingxi-advisor-mcp --profile operator --transport stdio \
      --batch-input /absolute/path/authorized-instances.jsonl

或：

    LINGXI_ADVISOR_BATCH_INPUT_PATH=/absolute/path/authorized-instances.jsonl

`lingxi.advisor.knowledge_preparation_capabilities` 的 `batch.configured` 表示该配置是否存在。
未配置时，单任务 `lingxi.advisor.prepare_historical_knowledge` 仍可使用，但
`lingxi.advisor.start_preparation_batch` 会明确失败，不再隐式读取当前工作目录。

## 4. 启动与挂载

安装 MCP extra：

    uv sync --extra mcp

启动 Runtime：

    uv run lingxi-advisor-mcp --profile runtime --transport stdio

启动 Operator：

    uv run lingxi-advisor-mcp --profile operator --transport stdio \
      --batch-input /absolute/path/authorized-instances.jsonl

两个入口都由 lingxi_advisor.adapters.mcp.server 完成依赖装配。仓库内部的
_register_runtime_tools 和 _register_operator_tools 仅用于 composition wiring
与测试，不从 lingxi_advisor.adapters.mcp 公开导出，也不是第三方 Host 接口。

Host 应直接读取 descriptor 并启动或连接 Server。安装后 descriptor 位于：

    <install-root>/host/runtime.json
    <install-root>/host/operator.json

## 5. 发行与安装

构建一个同时携带两个 Profile 的 release bundle：

    uv run python scripts/build_release_bundle.py --output-dir dist

Bundle 包含一个 lingxi_advisor wheel、两个 Skill/Agent Profile、两份 server
descriptor、本文和 Host 部署文档。版本和 Artifact contract 完全相同。

安装：

    python install.py install --bundle-root <bundle-root> \
      --install-root <install-root> --python <python>

当前发行不携带 Contribution Manifest。没有通用 Loader 前，正式启动信息只来自
Runtime/Operator server descriptor，工具列表由对应 MCP Adapter 的唯一常量生成
或强校验，避免出现重复事实来源。

运行 `install.py` 的 Python 可以与 `--python` 指定的目标环境不同；安装器会在
目标环境中读取已安装 package 并生成 Host descriptor。

卸载：

    python install.py uninstall --install-root <install-root> --python <python>

卸载不删除用户 Artifact、repository cache、worktree 或运行证据。

## 6. Python 与 CLI

次级 Python adapter 保留 search_lingxi_advisors、apply_lingxi_advisors 和
prepare_historical_knowledge。Canonical CLI 保留：

    lingxi-advisor-prepare
    lingxi-advisor-candidate-search
    lingxi-advisor-generate
    lingxi-advisor-mcp

Python 与 CLI 调用同一个 Core Package，不复制 MCP handler 或算法。

## 7. 配置、安全与存储

常用环境变量：

    LINGXI_ADVISOR_JUDGE_API_KEY
    LINGXI_ADVISOR_JUDGE_MODEL
    LINGXI_ADVISOR_GENERATOR_API_KEY
    LINGXI_ADVISOR_GENERATOR_MODEL
    LINGXI_ADVISOR_BATCH_INPUT_PATH

Runtime 未配置模型时可使用 Agent Host sampling；Operator 长任务通常应配置服务端
模型。GitHub、clone/fetch、refresh 和写入权限由 Server policy 拥有。

不要发送目标 solution patch、目标 test patch、hidden tests、credentials 或
Server 路径。历史 Issue、Patch、代码和 XML 都是不可信证据。Local Artifact
Store 是 V4 第一阶段的正式存储；不要求云端知识库。

## 8. 验证

    uv run pytest

Runtime 真实验收证明第一次 search → ensure → Artifact → apply，第二次禁止
Generation 且复用同一 Artifact；Operator 真实验收证明 start → poll → result
→ read。保留 run/request id、Artifact、状态、日志和调用记录；skip 和 mock
不算真实通过。

更多部署细节见
[Host 部署文档](docs/AGENT_HOST_DEPLOYMENT_ZH.md)。完整设计与逐项差异见
docs/LINGXI_ADVISOR_CAPABILITY_REFACTOR_ZH_V4.md 和
docs/LINGXI_ADVISOR_CAPABILITY_REFACTOR_V3_TO_V4_DELTA_ZH.md。
