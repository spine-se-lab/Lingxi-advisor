# LingxiAdvisor V4 Agent Host 部署与验收

V4 的外部 seam 是已组装的 Runtime/Operator MCP Server。Host 负责加载 Agent
Profile、加载 Skill、读取 server descriptor 并启动或连接 Server；Host 不构造
LingxiAdvisor 内部 capability 对象。

## 1. 交付目录

    skills/lingxi_advisor/
    skills/knowledge-preparation-operator/
    packaging/runtime-server.json
    packaging/operator-server.json

正式 bundle 只含一个 lingxi_advisor wheel。当前没有通用 Loader，因此不交付
Contribution Manifest；Runtime/Operator server descriptor 是唯一挂载事实来源。

## 2. Runtime 挂载

安装后的 host/runtime.json 描述：

    python -m lingxi_advisor.adapters.mcp.server
      --profile runtime --transport stdio

Runtime tools/list 必须严格等于：

    lingxi.advisor.search
    lingxi.advisor.apply

Runtime Agent Profile 与 Skill 只描述 search → apply。Search 最小调用只要求
issue_description；Apply 只接收 issue_description 和 knowledge_matches。
最小调用只检查已有且已审核的本地预检索知识。SWE-bench 风格任务继续以
`repo + instance_id + base_commit` 进入 live 检索；普通 GitHub issue 没有
instance id 或 base commit 时，以 `repo + issue_number` 作为 fallback，Server
负责补全 identity 与时间边界元数据。尚未登记的新 issue 使用
`repo + issue_description`，由 Server 自动识别并派生 path-free identity、解析请求
开始前的最新 commit，并建立请求时间 boundary。调用方不传 timestamp 或 null
占位字段。

Runtime Host 不应提供显式 prepare、Batch、Result 或 Read。Search 先复用有效兼容的
Artifact；Artifact 缺失、失效或不兼容时在 Server 内部自动调用现有 Codify.ensure
流程。repo-only 新 issue 执行有界 live retrieval。
Search 直接返回 XML，Apply 返回 status、content、source_artifact_refs 和 error。

两种 Generation 均 cache-first：缓存命中不重复 Generation。Light 的 cache miss
不读取 repository worktree；Grounded 的 cache miss 必须使用 Server 准备的
detached post-fix worktree，并在分析前后验证 HEAD、仓库根目录与 clean 状态。
Grounded 只读 Git 命令有硬边界，分析阶段不隐式 fetch；Summarizer 不使用工具。

若需要 Runtime 和 Operator，Host 应分别连接两份 descriptor，不能把 Operator
改造成 Runtime 超集。

## 3. Operator 挂载

安装后的 host/operator.json 描述：

    python -m lingxi_advisor.adapters.mcp.server
      --profile operator --transport stdio

Batch 输入由 Host 配置，不进入 Agent/MCP Tool 参数。部署时在 Operator command
追加：

    --batch-input /absolute/path/authorized-instances.jsonl

也可以由进程环境设置：

    LINGXI_ADVISOR_BATCH_INPUT_PATH=/absolute/path/authorized-instances.jsonl

JSONL 每行必须是一条公开任务实例，至少包含 `instance_id`、`repo`、
`base_commit` 和 `problem_statement`。文件路径、凭据和目标 Patch 不得写入实例。
Host 应先调用 `lingxi.advisor.knowledge_preparation_capabilities`，仅当 `batch.configured=true`
时启动 Batch。未配置不会影响单任务 Preparation，但 Batch 启动会明确失败。

Operator tools/list 必须严格等于：

    knowledge_preparation_capabilities
    prepare_historical_knowledge
    start_preparation_batch
    get_preparation_batch
    get_preparation_result
    read_prepared_knowledge

Operator Agent 加载 skills/knowledge-preparation-operator/。单任务调用
prepare → result → read；批量调用 start → poll → result → read。Skill 只说明
Codify Operation 工作流，不实现 Retrieval、Gate、Generation、Store 或 Worker。

Batch 状态由本地 Job Store 持久化；Worker 中断后可按同一 batch id 恢复。
Grounded 长任务仍使用 generation_mode=grounded_analysis。

## 4. Server authority

Host 和 Agent 不得传入目标 solution patch、目标 test patch、hidden tests、
credentials、repository path、cache path 或 worktree path。以下权限由 Server
policy 持有：

- live GitHub search；
- pre-retrieved 写入；
- metadata/cache refresh；
- repository clone/fetch；
- candidate、Top-K、响应体和 Batch 大小限制。

Server 对结果中的私有路径脱敏；read_prepared_knowledge 只接受同一 request
已发布的 XML basename。

## 5. Model fallback

Runtime 在服务端 Judge/Generator 未配置时，可使用当前 MCP session 的 Agent Host
sampling；sampling 必须与当前请求绑定。Operator 长任务通常使用服务端模型配置，
避免后台任务脱离原 MCP request 后失去 Host sampling context。

Host model fallback 不改变 Codify、Artifact identity 或 XML schema。

## 6. 安装后验收

1. installed lingxi_advisor 版本与 bundle.json 一致；
2. 两个 Skill 和两个 Agent Profile 均存在；
3. Runtime/Operator descriptor 与实际 tools/list 完全一致；
4. Runtime 只有 Search/Apply；
5. Operator 只有 Codify Operation tools；
6. Runtime Search inputSchema 只要求 issue_description；
7. Runtime Search 的可选 context schema 明确列出 repo、base_commit、instance_id、issue_number；
8. Runtime Apply inputSchema 只要求 issue_description、knowledge_matches；
9. Operator 可完成 start → poll → result → read；
10. bundle 和安装目录均不存在重复的 Contribution Manifest；
11. `batch.configured=true` 后 Operator 才启动批量任务。

## 7. 真实闭环

Runtime 第一次调用必须记录：

    search
    → real GitHub candidate selection / Gate
    → Codify.ensure
    → Artifact Store
    → apply

第二次 Search 通过 Artifact Store 复用有效知识，不额外 Generation，仍返回相同
Artifact ref/SHA/XML，Apply 继续保留来源。

Operator 必须记录：

    start_preparation_batch
    → get_preparation_batch 观察 running 与终态
    → get_preparation_result
    → read_prepared_knowledge

真实验收保留 run/request id、Artifact 路径、状态、日志和 MCP 调用证据。未配置
真实 GitHub/模型凭据可标记未验证，但 skip 或 mock 不算通过。

## 8. 卸载边界

安装器根据 .lingxi_advisor-install.json 删除 wheel、Skill、文档和 Host descriptor。
用户 Artifact Store、repository cache、worktree、输出与真实验收证据不在自动删除
范围内。

低层 _register_runtime_tools 和 _register_operator_tools 是仓库内部 wiring；
第三方 Host 示例或文档不得把它们当作公开交付接口。
