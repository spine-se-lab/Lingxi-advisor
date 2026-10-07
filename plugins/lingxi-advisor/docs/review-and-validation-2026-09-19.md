# LingxiAdvisor 0.8 核心与插件安装迁移：Review 与验证交接

编写日期：2026-09-19。面向代码 reviewer、宿主集成维护者和验收同事，可独立于聊天记录阅读。

## 1. 本次要达到什么结果

用户通过完整仓库 CLI、独立 Delivery CLI 或 Product Plugin Management 安装 Lingxi Advisor 后，即使安装来源目录被移走，仍能启动新的 MCP 进程、使用知识能力、检查安装和卸载。在线检索后的知识生成与离线知识准备共用核心业务实现，故障能被明确分类，已提交知识和用户数据不因管理操作丢失。

本次交付是插件 `0.3.0`、核心 `0.8.0`。Search/Apply、Light/Grounded、Operator 单任务与批次准备原来就存在；本次重点是安装责任调整、核心内部重构和运行故障修复。没有检索质量或速度提升的对照实验，也没有修改候选排序和安全过滤策略。

代码已推送两个仓库的 `main`。本文锁定下面的历史提交；之后主干已有其他变更，不能直接用最新 main 的测试结果替代本次验收。

## 2. Review 范围与依据

| 仓库 | 变更前 | 本次实现末端 | 已进入主干的提交 |
| --- | --- | --- | --- |
| [CodeHelix-Plugin](https://github.com/yiikou/CodeHelix-Plugin) | `ab147706bdd5505a77eaf420c9d8e5795aca43e1` | `72d23ea`（含实施证据） | `3d8093ec3494913403b8fcc358ae8c8155f52cbb` |
| [Lingxi-LingxiAdvisorGuidance](https://github.com/yiikou/Lingxi-LingxiAdvisorGuidance) | `83ec684` | `9f14a269f87927861f537bd8f4290325cdf9a57c` | 同实现末端 |

插件实现提交为 `2958725`、`1d847bf`，证据提交为 `72d23ea`。`3d8093e` 合入了当时远端的 Experience Advisor 更新；review 本次业务改动应使用 `ab14770..72d23ea`，复验当时发布快照可使用 `3d8093e`。不要把合并进来的 Experience Advisor 改动算作本次范围。

- [插件变更对比](https://github.com/yiikou/CodeHelix-Plugin/compare/ab147706bdd5505a77eaf420c9d8e5795aca43e1...72d23ea)：包含安装、共享 Kit 加固、生成 Delivery 和证据。
- [核心变更对比](https://github.com/yiikou/Lingxi-LingxiAdvisorGuidance/compare/83ec684...9f14a269f87927861f537bd8f4290325cdf9a57c)：核心重构和模型执行修复。
- [主 Issue #3](https://github.com/yiikou/CodeHelix-Plugin/issues/3)：本插件工作的关联入口；本文不修改或关闭 Issue。
- [安装协议][protocol]、[已安装包生命周期][lifecycle]、[业务数据规范][data-spec]：共享框架的责任和合同，链接锁定发布快照。
- [插件设计分析][analysis]：原始背景与改造理由；[插件使用说明][readme]：本次交付的配置与工具边界。
- [实施记录][progress]、[机器可读验收摘要][evidence]：2026-09-17 的历史实测。实施记录里的“尚未推送”是当时状态；发布状态由本文第 2 节更新。历史设计中的 TODO 不能直接当成当前未完成项。

## 3. 系统边界和代码组织变化

CodeHelix 负责安装与管理；Coding Agent 通过自身扩展机制加载 Skill 和 MCP；LingxiAdvisor 核心负责检索、判断、生成和业务数据。插件在重构前已经使用上游 wheel，本次不是首次抽出独立核心。

| 对象／术语 | 当前责任 | Reviewer 应确认的边界 |
| --- | --- | --- |
| PackageStore | Kit 保留按摘要锁定的完整执行包 | 安装后实际从这里执行，不只是备份源码 |
| Runtime | Kit 构建一个 Python 环境，两个 MCP 共用 | 插件不另建私有安装生命周期 |
| Config binding | 保存非敏感设置、包和环境引用 | 密钥不进入 binding、命令行或 runtime.env |
| Activation | 宿主接线、Skill 投影及其所有权记录 | Adapter 只修改所拥有的 Profile／字段；漂移保护有效 |
| DataRef | 引用真实知识、批次、运行输出、缓存、预检索目录 | 指向可读的实际数据；卸载保留这些目录 |
| LingxiAdvisor 核心 | GitHub、安全边界、Gate、生成、Artifact、Batch | 不依赖 Product UI，也不在插件重写业务 |

### 3.1 代码入口与建议阅读顺序

以下插件路径相对于 CodeHelix-Plugin；核心路径相对于 Lingxi-LingxiAdvisorGuidance。先读维护源，再核对生成物和锁，避免将归档或 vendored 依赖误认为手写业务代码。

| 优先阅读的文件 | 之前 → 现在 | 重点检查 |
| --- | --- | --- |
| 插件 `source/installer/installer.py`、`configuration.py`、`managed_layout.py`；共享 `plugin-kit/installation/orchestrator.js` | 私有安装器自行管理目录和生命周期 → Kit 管理事务，插件解释配置和部署引用 | prepare/commit/inspect/remove 是否使用同一所有权和部署身份 |
| 插件 `source/launcher.py`、`source/installer/adapters/` | 私有 runtime.env 与路径 → binding、已安装 Runtime 和启动环境 | 来源移走后路径仍有效；旧 binding／包命令不可混用 |
| 核心 `src/lingxi-advisor/api.py`、`composition.py`、`config.py` | 入口混合组装 → composition 集中组装，settings 一次性解析环境 | Apply 不构建生成器；缺失密钥也应形成稳定快照；密钥不出现在 repr |
| 核心 `internal/generation_service.py` | 文件／JSONL 衔接与重复组装 → 内存候选共享生成服务 | Codify 和 Preparation 共用缓存→生成→Artifact，保留锁内二次缓存检查和原子发布 |
| 核心 `internal/github/` | 约 4305 行混合模块 → transport、query、discovery、common、legacy CLI | 候选集合、查询联合、排序和同仓库／时间／目标修复隔离不变；正常运行不加载旧 CLI |
| 核心 `internal/knowledge_validation.py` | 多处 XML／摘要判断 → 共用校验 | 读回的是同一份已校验内容；合法 XML 被篡改也会因摘要不符被拒绝 |
| 核心 `internal/run_state.py`、`capabilities/codify/batch_preparation/{state,service}.py` | 状态和索引更新耦合 → 不可变 attempt result、manifest、派生索引 | 索引写失败不撤销已提交结果；索引可在锁保护下重建 |
| 核心 `internal/{execution,policy}.py` | 分散预算、重试与入口权限判断 → 核心共享策略和执行控制 | 无嵌套重试放大；取消后不再重试或发布；超时原因不混淆 |

上述核心路径均位于 `src/lingxi-advisor/` 下。插件完整路径前缀为 `plugins/lingxi-advisor/`。

构建边界也有变化：原来的源码 overlay 加固已进入核心正式提交；导入要求干净提交、完整测试和两次一致归档。独立 Delivery 带齐共享 Kit 使用的 5 个锁定 npm 依赖及许可证，并保留原始字节。两份 Delivery 中的重复 payload 是交付需要，不是两份业务实现。

### 3.2 使用者实际能观察到的变化

| 场景 | 现在应出现的行为 |
| --- | --- |
| 脱离安装来源运行 | 移走独立 Delivery 后，从最新宿主配置启动新 MCP 仍成功；保留的 Kit 可以检查和卸载 |
| 凭据轮换 | 启动环境读取密钥，无新 runtime.env，也无旧 dotenv 兜底；更换密钥后重启进程，无需重装 |
| OpenCode 配置 | 只管理 `mcp.lingxi-advisor` 和 `mcp.lingxi-advisor-operator` 两个 JSONC 字段，保留无关字段和注释，不整份备份含凭据配置 |
| 旧版迁移 | 核验旧安装记录和内容后接管；失败能恢复原接线；成功卸载不重新启用旧 runtime，旧私有目录暂保留 |
| Judge 推理输出 | 默认预算 4096→16384，可配置；截断、空输出、JSON／schema 失败不能被当成正常不相关 |
| Gate 结果 | 正常判断不相关为 `no_candidates`；无选中且判断过程失败为 `failed`，保留错误统计 |
| Grounded 工具预算 | 保留 20 次只读工具上限；超额请求得到未执行结果，最终整理阶段关闭工具；输出仍必须通过 XML 校验 |
| MCP 并行工具 | 一轮多个工具调用得到符合 MCP 消息合同的工具结果组织 |
| 执行失败 | 请求总预算到期为 `deadline_exceeded`；worker 网络超时仍归于 transport；认证、限流等错误保持分类 |
| 卸载 | 移除两个 MCP 接线和两个 Skill；业务数据保留，PackageStore／Runtime／Config 按共享生命周期保留 |

保持不变：两个 Skill、两个 MCP；Runtime export v1 仍只有一个 Runtime Skill、一个 Runtime MCP、Search/Apply 两个工具，Operator 独立。Operator 生成仍需自定义模型；Runtime 只有在宿主支持 MCP sampling 时才能回退宿主模型。插件不自动读取或修改 Chrys model profile。

## 4. 已有证据及其适用范围

以下都是 2026-09-17 完成并入库的验收记录，不是 9 月 19 日重新运行所得。同事复验时请另记日期、提交和环境。

| 验证层 | 历史结果 | 能证明什么／不能证明什么 |
| --- | --- | --- |
| 核心 | 223 通过，2 项 opt-in 真实 GitHub 测试跳过 | 核心回归通过；跳过不等于在线测试通过 |
| 插件 | 加载交付 wheel 的测试 47 通过 | 安装器、配置、MCP 启动和导出合同回归 |
| 共享 Kit | 166 通过；合并远端更新后再次 166 通过 | 当时快照的共享安装回归；不代表今天整个仓库全部通过 |
| LingxiAdvisor 契约与锁 | 17 通过 | 声明和 Delivery 摘要覆盖 |
| 真实宿主 | Chrys 0.20.1、OpenCode 1.18.25 × repo／独立包，共 4 通过；此前也测过 Chrys 0.18.1 | 实际宿主加载、新 MCP、来源移走后检查／移除；0.20.1 checkout 有既存修改，未被本轮改动 |
| 构建 | 两次核心归档一致；全新 checkout 重建 288 个 Delivery 文件逐字节一致 | 本次快照构建可复现 |
| 真实公开任务 | Requests #5714，44 条安全历史候选，选中历史 #1228；Light 和 Grounded 各生成一份 XML | 两模式生成、Search/Apply、缓存重放及 Operator 单任务／批次／读回完成；不是效果基准 |
| Product | 安装与漂移展示通过 UI；来源移走后通过真实管理后端卸载 | 5 个 DataRef 可读；两个 MCP 和 Skill 消失；706 个数据文件摘要不变。没有完成 UI 移除确认框操作 |
| 宿主 sampling | 官方 MCP 客户端回调接真实 DeepSeek，受控历史 fixture；Light 4 次、Grounded 8 次模型调用 | 生成、缓存、Apply 和并行工具路径；不等于完整 Chrys 对话验收 |

核心归档 SHA-256：`693af067eae4050756438b9a2d36f0b32b783cb7dbf61bec6991c7c452dedf86`。

公开 Light 制品 SHA-256：`6cf63a12df06e5f2fcb309ae1ea9d90a85781f8d9baff330e97170898962a10c`；Grounded：`af67199015a984720925d300e801894932f3717d429e4fabcbb19fe68ed060a6`。这些摘要用于核对原始制品，不要求同事重新调用模型得到相同文本或摘要。

原始真实生成发生在核心 `d7c9d69`；最后的 `9f14a26` 调整了异步 deadline 分类，之后使用最终安装版本复验了缓存、Apply 与 Operator 全链路。两种来源已在 JSON 中分别记录。706 个数据文件中的 6 个 XML 包含缓存和导出副本，不代表生成了 6 份独立知识。

## 5. 同事如何复验

### 5.1 固定版本并跑自动化回归

以下示例针对 macOS／Linux，要求 Git、Node ≥18、npm、Python ≥3.10，以及依赖下载网络。使用新的目录和虚拟环境；命令中的相对路径以对应仓库根目录为准。

```sh
mkdir lingxi-advisor-review
cd lingxi-advisor-review
git clone https://github.com/yiikou/CodeHelix-Plugin.git plugin
git -C plugin checkout --detach 3d8093ec3494913403b8fcc358ae8c8155f52cbb
git clone https://github.com/yiikou/Lingxi-LingxiAdvisorGuidance.git core
git -C core checkout --detach 9f14a269f87927861f537bd8f4290325cdf9a57c
```

在 `plugin` 目录执行。安装的是实际交付 wheel，避免误测到本机别处的核心源码：

```sh
npm ci --ignore-scripts --no-audit --no-fund
python3 -m venv .review-venv
.review-venv/bin/python -m pip install pytest PyYAML
.review-venv/bin/python -m pip install 'plugins/lingxi-advisor/delivery/opencode-1.x/runtime/lingxi-advisor-extension-0.8.0/runtime/lingxi-advisor-0.8.0-py3-none-any.whl[mcp]'
node bin/codehelix-plugins.js validate lingxi-advisor
npm test
.review-venv/bin/python -m pytest plugins/lingxi-advisor/source/tests --ignore=plugins/lingxi-advisor/source/tests/test_real_hosts.py -q
```

验收：validate 成功；该快照 Kit 166 项、插件 47 项通过。若数目不同，先核对提交、收集结果和跳过原因，不能仅修改预期计数。插件测试中 `test_managed_mcp.py` 会启动交付核心，检查 Runtime 两个工具和 Operator 六个工具。

在 `core` 目录使用另一个环境运行：

```sh
python3 -m venv .review-venv
.review-venv/bin/python -m pip install -e '.[test]'
.review-venv/bin/python -m pytest -q
```

不设置 `LINGXI_ADVISOR_REAL_INSTANCE_JSON` 时，在线 GitHub 集成默认跳过；历史基线为 223 通过、2 跳过。`test_real_host_sampling.py` 名称里的 real 指实际协议／进程集成，不能仅由测试名推断发生了真实计费模型调用。

代码 review 后可重点查看 `test_execution_contract.py`、`test_batch_commit_recovery.py`、`test_core_knowledge_contract.py`、`test_grounded_hardening.py`、`test_host_sampling.py`、`test_resolved_configuration.py`，确认测试覆盖失败路径，而不只覆盖成功返回。

### 5.2 真实宿主生命周期复验

在 `plugin` 目录设置实际宿主位置：

```sh
export LINGXI_ADVISOR_REAL_CHRYS=/absolute/path/to/chrys-checkout
export LINGXI_ADVISOR_REAL_OPENCODE=/absolute/path/to/opencode-executable
.review-venv/bin/python -m pytest plugins/lingxi-advisor/source/tests/test_real_hosts.py -q -rA
```

Chrys 使用已配置好环境的 checkout；OpenCode 变量是可执行文件路径。可选 `LINGXI_ADVISOR_REAL_NODE` 指定 Node。建议先用历史验收版本；新版宿主应另记版本和结果，不能直接视为同一覆盖。

验收应为四种组合均通过：两个宿主 × repo／独立包。测试使用临时 config、home、data，并覆盖重复安装、移走独立 Delivery、从 PackageStore 启动新 MCP、保留 Kit 的 inspect/remove 和数据文件保留。两项 MCP evidence 均应为 connected，并有真实 Profile 或 OpenCode config 证据。未设置宿主变量时会 skip，不能登记为通过。

此测试刻意使用 fixture GitHub token，并移除自定义模型环境；它验证宿主加载和安装生命周期，不验证在线检索或知识生成。

### 5.3 真实模型和业务链路复验

使用隔离 config-root、CodeHelix home 和 data_root，按[插件 README][readme]配置非敏感模型参数。历史使用 Chrys 的 DeepSeek V4 Flash profile，对应模型 `deepseek/deepseek-v4-flash-0731`、endpoint `https://openrouter.ai/api/v1`。复验前确认服务仍提供该模型；如果换模型，记录实际名称，结果作为新环境验收。

通过启动环境提供 `GITHUB_TOKEN`、`LINGXI_ADVISOR_MODEL_API_KEY`（也可分别配置 Judge／Generator key）；不把密钥放进命令参数、文档或验收附件。Chrys profile 的变量解析由宿主或验收侧完成，不是插件自动导入。

可采用相同公开任务：`psf/requests` #5714，base commit `c2b307dbefe21177af03f9feb37181a89a799fcc`，只输入公开标题／正文及仓库身份，不注入目标修复补丁或隐藏测试。历史候选和 LLM 输出会变化，不要求重跑仍精确得到 44 条候选或选中 #1228。

以下是业务验收步骤，不是已经入库的一键重放脚本。各工具的输入字段以安装后 MCP `list_tools` 返回的 schema 和两个 Skill 为准；保存调用入参、脱敏结果及制品摘要。

| 步骤 | 操作与通过标准 |
| --- | --- |
| 1. 确认入口 | 从最新宿主配置启动两个 MCP，读取工具列表；Runtime 只有 Search/Apply，Operator 有能力查询、prepare、start/get batch、get result、read 六项 |
| 2. 首次生成 | Light 与 Grounded 分别使用独立数据根运行 `lingxi.advisor.search`；确认产生新的有效 XML、有来源和摘要。空缓存运行才可证明真实生成 |
| 3. 应用知识 | 将实际返回的知识引用传给 `lingxi.advisor.apply`，内容可读且摘要一致；不要求 Apply 再配置生成器 |
| 4. 缓存重放 | 相同输入重放，记录命中缓存且没有新增生成；必要时结合模型调用日志核实，不能用“返回更快”代替证据 |
| 5. 单任务准备 | 调用 `lingxi.advisor.knowledge_preparation_capabilities`、`lingxi.advisor.prepare_historical_knowledge`，检查能力和结果。明确标记是新生成还是复用已有知识 |
| 6. 异步批次 | 设置 `batch_input_path` 指向公开任务 JSONL，调用 start/get/result/read；批次最终 completed，记录可观察到的状态、逐项结果和读回 XML。极快完成不要求一定轮询到 running |
| 7. 失败路径 | 用受控 fixture／自动化测试核对截断输出、Gate schema 失败、摘要篡改、派生索引失败、取消和 deadline。有效不相关与执行错误必须区分 |

默认 `allow_clone`、`allow_fetch` 关闭。Grounded 所需仓库应预先准备，或在隔离验收配置中明确启用所需能力；权限拒绝不能误诊为模型故障。总请求预算 900 秒；若到期，记录失败与候选是否已持久化，再将重试单独登记，不把冷调用改写成成功。

### 5.4 安装入口、迁移与卸载人工复验

真实宿主自动化复验之外，还需要集成同事覆盖实际用户入口。

| 场景 | 执行方法 | 可观察的通过标准 |
| --- | --- | --- |
| 完整仓库 CLI | 隔离环境执行 `npx . lingxi-advisor install ...`，具体 target／config 参数见 README | 展示配置与计划，经安装后实际调用 MCP，不止验证 help |
| 独立 Delivery CLI | 复制对应 Delivery 到仓库外，按 README 用本地 npx 安装；随后移走复制来源并启动新 MCP | 不依赖开发仓库；已安装 PackageStore 和保留 Kit 能运行、检查和移除 |
| Product | Plugin Management 中配置、确认计划、安装、刷新；移走来源再刷新和使用 | 状态与真实 MCP 一致；5 个 DataRef 指向可读数据；UI 移除确认单独记录是否完成 |
| 配置漂移 | 备份隔离配置后，修改插件拥有的一个 MCP 字段并尝试移除 | 检查显示 drift，移除被拒绝且配置未被破坏；恢复原值后才继续正常移除 |
| 旧 0.7 升级 | 在另一隔离环境用基线提交安装，再切换本次提交升级；另以受控失败测试验证回滚 | 新接线可用，失败保留原接线；成功后卸载不复活旧命令；不可接管无所有权的内容 |
| 数据保留 | 卸载前为实际数据目录建立逐文件 SHA-256 清单，卸载后再次计算 | 两个 Skill 和两个 MCP 接线消失，业务文件路径及摘要保持；不要以空目录或占位文件代替业务数据验收 |

PackageStore／Runtime 的保留属于本次生命周期设计，不是“卸载失败”。验证来源独立性时应启动新进程，旧进程继续运行不能单独作为证明。升级后须重新读取宿主配置；旧命令绑定新 Config 被拒绝是身份校验，不应为通过测试而绕过。

## 6. 限制、待复验项与交付判定

已观察限制：首次公开 Light 冷调用耗尽 900 秒，复用已保存候选后才完成；同步 HTTP 依赖 I/O timeout 和协作取消，不能保证立即硬终止。Windows 未原生实跑。历史 Product 移除经真实后端完成，UI 确认框操作仍待人工补验。受控 sampling 验证不能替代完整 Chrys 对话效果评估。

历史宽范围 Python 筛选还遇到无关 `swe-pro-kit-with-lingxi-advisor` 的两项基线 Delivery 漂移失败。本轮未修该插件，不能声称全仓 Python 测试通过；复验若出现相同失败，应记录复现提交和归属，再判断是否影响本插件。

原始完整模型脚本和日志有一部分仅保存在实施机器临时目录，仓库长期保留的是实施说明与 JSON 摘要；本文不承诺这些临时路径仍可访问。需要审计原始事件时应另取日志，或按第 5 节重新运行并归档证据。不要把缺失的日志当作已被重新检查。

建议分工与输出：

| 责任人 | 需要给出的 review／验收输出 |
| --- | --- |
| 核心 reviewer | 模块边界、业务不变量和失败语义是否成立；指出具体文件、触发输入和后果 |
| 插件／Kit reviewer | 包身份、配置所有权、密钥、迁移、来源独立性和数据保留是否符合公共规范 |
| 宿主／Product 验收同事 | 各入口、宿主版本、真实工具调用、Product UI／后端、卸载后实际状态及证据 |
| 实施维护者 | 对发现的问题复现、修复、补回归；若核心变动，重新导入锁定制品并构建两份 Delivery |

建议回传以下记录；“未执行”和“跳过”都应保留，不自动折算为通过：

```text
Reviewer / 日期：
插件提交 / 核心提交 / archive SHA-256：
OS / Python / Node / Chrys或OpenCode / Product版本：
模型 / endpoint / sampling或自定义模型（不含密钥）：
自动化结果（通过、失败、跳过及原因）：
repo CLI / 独立CLI / Product：
Light首次生成 / Grounded首次生成 / Apply / 缓存重放：
Operator单任务 / batch / result / read：
来源移走后新进程 / 漂移保护 / 卸载前后数据摘要：
未验证项和已知限制：
问题列表（文件、输入、预期、实际、脱敏证据）：
结论：通过 / 有条件通过（写明条件） / 不通过
```

完成标准是 review 意见已闭环，所选宿主和安装入口上的关键行为有可观察证据，且所有未覆盖范围被明确记录。已有历史测试为复验提供基线，不能替代同事本次签署的结果。

[protocol]: https://github.com/yiikou/CodeHelix-Plugin/blob/3d8093e/docs/specifications/custom-installer-protocol.md
[lifecycle]: https://github.com/yiikou/CodeHelix-Plugin/blob/3d8093e/docs/specifications/installed-package-lifecycle.md
[data-spec]: https://github.com/yiikou/CodeHelix-Plugin/blob/3d8093e/docs/specifications/plugin-data.md
[analysis]: https://github.com/yiikou/CodeHelix-Plugin/blob/3d8093e/plugins/lingxi-advisor/docs/analysis-2026-09-16.md
[readme]: https://github.com/yiikou/CodeHelix-Plugin/blob/3d8093e/plugins/lingxi-advisor/README.md
[progress]: https://github.com/yiikou/CodeHelix-Plugin/blob/3d8093e/plugins/lingxi-advisor/docs/implementation-progress.md
[evidence]: https://github.com/yiikou/CodeHelix-Plugin/blob/3d8093e/plugins/lingxi-advisor/docs/verification-2026-09-17.json
