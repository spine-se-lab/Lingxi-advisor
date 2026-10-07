# Task Pattern 安装迁移与核心重构实施记录

更新：2026-09-17。目标是让 LingxiAdvisor 通过完整仓库 CLI、独立 Delivery CLI 和 Product Plugin Management 安装后，脱离开发目录继续运行和管理；在线检索与离线准备共用同一核心业务实现。

安装迁移、核心重构和本轮约定的本机验收已完成。真实公开 GitHub 任务的 Light 与 Grounded 生成、缓存复用、Apply、Operator 单任务与批次读取均通过；源码来源移走后的 Product 卸载保留了全部业务数据。以下分别说明当前实现、实测证据和适用边界。

## 边界和交付

CodeHelix Kit 拥有 PackageStore、Python Runtime、非敏感 Config binding、Skill 投影、Activation 所有权和安装事务。插件 Adapter 只建立 Chrys Profile/OpenCode MCP 接线，并验证真实宿主加载。LingxiAdvisor 核心拥有 GitHub 检索、安全/时间边界、LLM Gate、Light/Grounded 生成、Artifact 与 Batch 业务。

依据：[主 Issue #3](https://github.com/yiikou/CodeHelix-Plugin/issues/3)、[原分析与目标](analysis-2026-09-16.md)、[插件结构和使用](../README.md)、[安装协议](../../../docs/specifications/custom-installer-protocol.md)、[生命周期规范](../../../docs/specifications/installed-package-lifecycle.md)、[数据规范](../../../docs/specifications/plugin-data.md)。本轮不另外拆建插件缺陷 Issue。

核心在隔离上游 worktree `lingxi-advisor-core` 实施并提交为 `9f14a269f87927861f537bd8f4290325cdf9a57c`，版本 `0.8.0`。导入要求干净已提交快照，完整测试通过、两次归档字节一致。archive SHA-256 为 `693af067eae4050756438b9a2d36f0b32b783cb7dbf61bec6991c7c452dedf86`。原始上游 checkout 和既存缓存未修改。插件仓版本为 `0.3.0`，实现与运行加固已在本地提交为 `2958725`、`1d847bf`，尚未推送。

## 已实现的结构

| 改造对象 | 当前实现及可观察行为 |
| --- | --- |
| 安装生命周期 | 两个 Target 使用相同 managed prepare/commit/inspect/remove；一个 Runtime、两个 Skill、两个 MCP |
| Secret | 启动环境读取；无新 runtime.env；旧 dotenv 不参与配置；新进程可接收轮换值 |
| 宿主所有权 | OpenCode 仅记录两个 MCP JSONC 字段；无关字段、注释和凭据不进入备份；Chrys Profile 单文件验证 |
| 旧安装迁移 | 校验旧记录和实际内容后接管；失败仍可恢复旧接线；成功后的移除停用接线，不重新启用旧 runtime；旧私有目录暂保留 |
| 数据与 export | DataRef 指向真实业务目录；移除保留数据；runtime export v1 仍为一个 Skill、一个 MCP、两个工具 |
| 配置与组装 | composition 统一能力组装；resolved settings 对环境做一次快照；Apply 不需要生成器配置 |
| 生成 | 内存候选 → cache/生成 → Artifact 共享服务；CLI 仅适配 JSONL 输入；保留锁内二次缓存检查与原子发布 |
| GitHub | transport、query、discovery 与 legacy CLI 分离，保留原安全过滤与完整候选集合语义 |
| 制品校验 | Artifact/cache/preparation/read 共用 XML 和摘要校验；合法 XML 被修改也会被 digest 检查拒绝 |
| 批次提交 | 显式状态；不可变 attempt result → manifest → 可重建索引 |
| 执行控制 | 核心策略、分类失败、共享时间预算和协作取消；生成器独占重试，避免 SDK 重试相乘 |
| 独立 Node 入口 | Kit 所需 5 个锁定 npm 依赖随 Delivery 的 `kit/node_modules` 交付，含原许可证；已核对 npm tarball 的 SHA-512 和逐文件内容 |

## 本轮已得到的证据

这些证据覆盖安装、宿主加载、真实业务调用和移除后的实际状态；公开 GitHub 实测与受控 fixture 实测分别列出。

| 场景 | 结果与边界 |
| --- | --- |
| 核心 clean import | 干净提交完整测试 223 项通过、2 项真实 GitHub 测试明确跳过；两次 release 构建一致 |
| 共享 Kit | 最终全套 Node 回归 166 项通过，包括拒绝执行未被 Delivery lock 覆盖的 npm bin |
| 插件 | 加载已交付 wheel 的插件测试 47 项通过，包括独立依赖解析和旧记录切换回归 |
| 真实宿主生命周期 | Chrys 0.18.1 和 0.20.1 分别与 OpenCode 1.18.25 实跑 repo/独立包四组，均 4 项通过：安装、重装、新 MCP 进程、移走独立来源、检查、移除和保留数据 |
| 实际 CLI | 完整仓库与独立 Delivery 的 npx 安装/移除均通过，验证 Skill 已消失、用户数据仍在；证据目录 `lingxi-advisor-cli-3f6fc05a` |
| 实际 legacy 升级 | 从 git 基线原样安装 0.7，切换到 managed 0.8，真实宿主/MCP 自检通过；移除两个 MCP 字段和 Skill，旧数据保留；证据目录 `lingxi-advisor-legacy-9cd3xkuk` |
| Product UI | 隔离 OpenCode 中完成真实配置、计划确认和安装，Receipt `4e7771e10c48482e8699457546dfe7fa`；来源移走后 UI 仍显示 Installed，可刷新，提供移除入口 |
| Product 最终升级与移除 | 最终核心升级 Receipt `05540b70d757452b9c6ca7e5e6f87911`；来源移走后通过真实 Product 后端移除，Receipt `2ff74ba9b7fe44bf9fc02c44f3f5e2c1`。两个 MCP 字段和两个 Skill 均移除，706 个数据文件逐文件摘要未变，含两份缓存知识及其导出副本 |
| LingxiAdvisor 声明与锁 | 最新构建专属契约及 Delivery lock 测试 17 项通过 |
| 公开 GitHub Grounded 全链路 | Requests #5714 检索后选中历史 #1228，真实 DeepSeek 生成 1 份知识；最新安装版本的 Search/Apply、缓存复用、Operator prepare、异步 batch/get/result/read 均通过，批次从 running 到 completed，读回 XML 35,946 字符 |
| 公开 GitHub Light 全链路 | 同一公开任务与通过 Gate 的历史候选，真实生成 1 份知识；Search/Apply、缓存复用、Operator prepare、异步 batch/get/result/read 均通过，读回 XML 31,745 字符 |
| 官方 MCP sampling | 真实 DeepSeek Light 调用 4 次、Grounded 调用 8 次，各生成 1 份制品；再次搜索命中缓存且无新增模型调用，Apply 通过。Grounded 包含并行工具与 XML 修复；受控历史 fixture，非完整 Chrys 对话 |
| Product DataRef | 最终升级后再次移走来源，5 个 DataRef 均仍绑定到数据根，能读取真实知识、批次、运行结果、缓存与预检索候选 |
| Product 漂移保护 | 修改 Runtime enabled 字段后，UI 显示 Local changes detected；实际 Product remove 返回 2 并拒绝移除，配置未变；之后恢复原字段 |
| 全新 Git checkout | 从暂存树完整归档到仓库外，重建两份 Delivery；288 个文件逐字节摘要一致，独立入口 help 通过。已保留 vendored npm 的原始换行，避免 Git 改写锁定内容 |
| 冷/热 npx | 根入口、Delivery 和仓库外复制包的 help 均通过；后续完整安装发现的 worker 依赖问题已修复并重跑独立安装 |
| 真实自定义模型 | Chrys DeepSeek V4 Flash profile，经宿主环境模板解析；受控历史补丁 Light 生成 3 次真实调用、1 份制品、0 失败；撤去密钥重放 cache_hits=1、generated=0 |

真实 Light fixture 制品 SHA-256：`311641f668e7ff15e98ac13e248b4a675cba5c364bba133e621ba5957123f533`。详细证据在临时目录 `lingxi-advisor-real-model-f8p4y0t4/verification.json`。没有密钥值写入验收记录。

实际独立 CLI 暴露过“help 可用但 worker 找不到 jsonc-parser”；已通过锁定 payload 解决。实际 legacy 升级暴露过“写入新命令后仍对照旧命令 hash”；已改为精确目标内容通过、其他内容仍要求旧所有权校验，回归同时验证任意外来命令仍被拒绝。

## 真实模型验收中发现并修复的问题

公开 Requests issue #5714 检索得到 44 条通过安全过滤的历史候选，任务输入不含目标修复补丁。原 Judge 的 4096 个输出 token 被推理全部消耗，返回 `finish_reason=length` 和空白正文。默认额度已提高至 16384，并提供 `judge_max_output_tokens` 非敏感配置；宿主 sampling 使用同一额度。截断回复不会被当成有效判断，无选中且 Gate 有调用、JSON 或 Schema 错误时结果为 `failed`，有效相关性否定仍为 `no_candidates`。[OpenRouter 输出额度说明](https://openrouter.ai/docs/api_reference/parameters)解释了推理与正文共用额度的行为，实测对照记录证实本例的具体原因。

Grounded 首次分析请求超过 20 次工具调用时直接失败。核心保留原读取上限，加入剩余预算提示，为超额请求返回未执行结果，并为最终总结关闭工具。回归验证实际执行次数不越界、每个工具调用有对应结果且输出仍经过 XML 校验。公开样例修复后生成有效知识；真实 MCP sampling 暴露的并行工具结果消息问题也已修复，并由 MCP SDK 自身的消息校验覆盖。

Light 首次冷调用在检索、Gate 与生成合计 900 秒后到期，未发布制品。请求总预算保持 900 秒；修复的是空 TimeoutError 报告，并确保 worker 自身网络超时不被误标为请求到期。该次调用启用了 `update_preretrieved`，通过 Gate 的候选已经持久化，重试复用候选后完成真实生成。这个冷启动超时保留为已观察到的运行限制，成功重试不代表任何任务都能在一次请求中完成。

在并行验收期间升级安装后，旧进程继续完成生成，但验收脚本用此前保存的命令新建 Operator 进程时，被更新后的 binding 拒绝。脚本改为读取最新宿主配置后，两种模式的完整链路均为 `completed`；未放宽 PackageStore 身份校验。

## 证据索引与范围

可随仓库长期保留的机器可读摘要见 [verification-2026-09-17.json](verification-2026-09-17.json)，包含版本、测试计数、制品摘要、批次状态和数据保留结果，不含凭据。

真实公开任务的证据位于本机临时目录 `lingxi-advisor-product-uusaakna`。`installed-light-generation-succeeded-before-upgrade-restart.json` 和 `installed-grounded-generation-succeeded-before-upgrade-restart.json` 记录原始生成、Apply 与缓存复用；这两份记录的最终失败属于上述旧命令启动问题。读取最新配置后的完整成功记录分别为 `installed-light-verification.json`、`installed-grounded_analysis-verification.json`。`product-data-verification.json` 和 `product-removal-verification.json` 记录数据引用与移除后状态。

| 模式 | 公开历史知识制品 SHA-256 |
| --- | --- |
| Light | `6cf63a12df06e5f2fcb309ae1ea9d90a85781f8d9baff330e97170898962a10c` |
| Grounded | `af67199015a984720925d300e801894932f3717d429e4fabcbb19fe68ed060a6` |

- 最终交付再次实跑 Chrys 0.20.1 与 OpenCode 1.18.25 的 repo/独立包四组生命周期，4 项通过。Chrys checkout 有既存修改，本轮没有改动它；Chrys 0.18.1 的先前四组验收也已通过。
- Product 安装和漂移展示通过真实 UI 验证；浏览器工具未能处理移除确认框，因此最终移除通过同一 Product 管理后端执行，不声称 UI 确认操作已完成。
- MCP sampling 使用官方客户端回调和真实 DeepSeek，输入为明确标注的历史 fixture，不等于完整 Chrys 对话效果评测。
- 较宽的仓库测试筛选包含 `swe-pro-kit-with-lingxi-advisor`，其两项失败来自既有 Delivery 漂移：当前资产字节与 git 基线一致，基线 lock 已不匹配。本轮未修改该插件，不宣称全仓 Python 回归通过。
- Windows 未原生实跑。同步 HTTP 不能被硬杀，取消依靠预算与后续检查阻止重试和发布；不宣称所有平台、全部失败点都能瞬时回滚。
