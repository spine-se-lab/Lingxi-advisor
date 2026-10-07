# Lingxi Advisor 安装 v2 迁移指南

状态：设计及待办，**尚未完成适配**。核实日期：2026-09-15。插件：`lingxi-advisor 0.2.0`。
追踪 Issue：[#3](https://github.com/yiikou/CodeHelix-Plugin/issues/3)；完整正文见 [install-v2-migration-issue.md](install-v2-migration-issue.md)。

基线：[统一安装设计](../../../docs/specifications/plugin-installation-unification-overview.md)、
[生命周期合同](../../../docs/specifications/installed-package-lifecycle.md)、
[custom 协议](../../../docs/specifications/custom-installer-protocol.md)。共享 `managed_install` core 正在实施，以下不是已发布能力。

## 1. 结论与现状

工作量 **M**，适合在 Memory/Experience 之后接入；难点在 Secret 生命周期、上游产物和双宿主激活，而非源码 Patch。
以往 600–1,200 行只是粗量级，取决于上游启动参数与兼容导出改动。

- 上游由 `source/upstream/lingxi-advisor-extension-0.7.0.zip` 和 import lock 固定。
- Target 是 Chrys `0.20` 和 OpenCode `1.x`，当前版本门禁，**没有 Chrys 源码 Patch**。
- 两个 Skill：`lingxi-advisor`、`knowledge-preparation-operator`。
- 两个 MCP Server 用同一个 `lingxi-advisor-mcp` 命令，分别 `--profile runtime` / `operator`；
  **两 Server 共用一兼容 Python Runtime，不默认建两个 venv。**
- Chrys 有 `LingxiAdvisor` Profile；OpenCode 没有此 Profile 是 optional surface 差异，不应判失败。
- 当前 `config_root/lingxi/advisor/` 同时承载 release、venv、`config/runtime.env`、data、capability export。
- `_env_bytes()` 将 GitHub token/model key 写入 `runtime.env`，即使 `0600` 也不符合新合同；
  `_desired_files()` 安装时给 Skill 追加 defaults，也不符合 canonical Skill 原样链接的目标。
- 2026-09-15 实际 `npx . validate lingxi-advisor` 通过（2 Targets、2 Deliveries）。
  本次未重跑历史提及的全仓合同/build 测试，故不再将旧文档中的退出码、data label 或 clean-build 问题断言为当前确定失败；
  迁移时须实际复查。

## 2. 内容、环境、数据与 Agent 的关系

| 内容 | 迁移后位置/关系 | 责任 |
|---|---|---|
| 上游固定 release、MCP 实现、两个 Skill、Profile 模板、launcher/Adapter、管理入口 | 完整 Delivery 的 `~/.codehelix/package-store/` 快照 | 贡献者打包，框架校验物化，不依赖原 checkout |
| Python 依赖与 `lingxi-advisor-mcp` 命令 | 一个 `~/.codehelix/runtimes/lingxi-advisor/` Python 环境 | 框架准备；插件提供 artifact、解释器、命令 |
| Skill 激活 | Agent Skill 目录中的 symlink/copy | 框架投影；安装时不再改 SKILL.md |
| 两 MCP 注册、Chrys Profile、OpenCode JSONC 配置 | 所选 Agent 实际配置位置 | Host Adapter 渲染 Store/Runtime launcher 引用，不嵌 Secret |
| 非敏感 model name/base URL、allow-update、数据根 | `~/.codehelix/config/` 部署配置 | 框架保存，贡献者声明读取 |
| GitHub token pool、model API key | 启动环境或外部 Secret provider | CodeHelix 启动时注入；独立启动 Agent 时由调用者部署环境注入 |
| knowl_cache、preparation batch、outputs | 保留 `config_root/lingxi/advisor/data/` 或显式外部 data root | 只登记 DataRef，不强制搬迁；升级/卸载保留 |
| `lingxi.advisor.runtime/v1` export | 状态引用，必要时保留兼容文件作为 activation | 不复制数据、含 Secret 或引用旧 checkout/env file |

MCP Server 固定实现在 Store，启动用 Runtime 的 Python/依赖；Agent 拉起的进程不是要落盘的第三份 Server。

## 3. 贡献者具体待办

### 3.1 上游打包与一个 Runtime

1. 保留 import lock，在 build 生成自包含、固定内容的 MCP artifact；解包及 Skill augmentation 不在安装时改变 Store。
2. 两 Target 增加 `managed_install.schema: codehelix.managed_install/v1`；
   `runtimes` 声明一个 Python runtime，`source` 是 Delivery 内真实可安装包/wheel，
   `command` 是 `lingxi-advisor-mcp`，`python` 为已验证版本。不要把未经验证的 zip 当安装 source。
3. 两个 Server 共用 `request.managed.runtimes[<runtime-id>]`，保留 runtime/operator 参数差异；
   不在目标 config 内再造 release/venv/current-state。
4. core 能创建 venv 和安装指定 artifact，不等于传递依赖全部锁定。
   提供 dependency lock/wheel 方案并补冻结安装/校验；解释器、平台、依赖变化应改变 Runtime 身份。

### 3.2 Secret 与配置拆开

- 停止生成含真实 Secret 的 `runtime.env`；调整 launcher/上游 Adapter，不将值写进 env file、argv、Agent JSON/YAML、
  config/state/Receipt、日志或 Store。仅改权限不算完成。
- 保留 `GITHUB_TOKEN` 与 `GITHUB_TOKEN_1`…`GITHUB_TOKEN_15` 轮换池，声明完整白名单。
  `LINGXI_ADVISOR_MODEL_API_KEY` 只在所选模型模式需要时校验，缺失只报告变量名。
- 非敏感 endpoint/model/allow-update/data-root 可写部署配置；launcher 解析配置，只向子进程传必要环境。
  Agent 独立重启时不能依赖原 CodeHelix UI 或安装进程仍在，更不能回退读取持久 Secret。
- Chrys sampling 与 custom model 两条路径分别验收；OpenCode sampling 探测实际版本/客户端，
  不把历史“不支持”推断为所有未来版本的永久限制。
- 不复制旧 `runtime.env` 的 Secret。新启动路径确认可用后按明确归属/迁移计划处理旧生成文件，
  未知用户文件保留并报告，不回显其内容。

### 3.3 狭窄 Host Adapter 与能力门禁

Chrys 只处理 Profile/MCP/Skill 落点及 loader/schema 探针；OpenCode 处理 JSONC MCP 注册和 Skill 目录，
保留无关配置/注释。`managed_install.skills` 声明两个投影，`target_paths` 枚举 Profile、MCP 配置、兼容 export 等精确文件，
不能登记整个 data root。

从 `request.managed.package_root`、`runtimes`、`config_ref`、`skill_activations` 获取路径，
保留统一 `check/plan/install/verify`。硬版本改为真实能力门禁，区分已验证、预检查通过但未验证、阻断。
当前 verify 中整个目标 git tracked 状态比较应收窄到真实依赖的 loader/schema/注册能力，无关代码变化不能让无源码 Patch 插件失效。

### 3.4 兼容导出与 legacy

保持 `lingxi.advisor.runtime/v1` contract 或显式升版，输出稳定 launcher/Runtime/DataRef，不遗留 Secret env-file 路径。
operator 是否加入 export 属于显式契约演进，不能悄改现有消费者含义。可以保留既有导出文件路径作为兼容 activation。

按 import checksum/ownership record 接管旧 release、venv、skills、MCP/export；新部署验证后再清理已知旧运行资产。
知识、batch 和 outputs 保留。被其他部署引用的导出不能无提示破坏；但 core 当前没有跨插件依赖解析器，
先定义引用检查/迁移约束，**不要把本期扩大成全局组合器**。

## 4. 分工与验收

框架负责统一 CLI/Product 计划、Store、Runtime、symlink/copy、状态、精确回滚与独立管理入口；
贡献者负责两 MCP 参数/契约、环境白名单、Host Adapter、上游锁定、legacy 迁移与真实功能证据。
若改用 `external/system` ref，它目前只记录绑定，插件仍需健康探测。

- [ ] build/validate/协议/安全合同通过，连续两次 clean build 无 diff；记录测试日期和 artifact digest。
- [ ] Chrys、OpenCode 各真实安装并实际加载两个 Skill；symlink/copy 均有覆盖。
- [ ] 两 Agent 各自真正唤醒两个 MCP，完成 initialize、tools/list，不以 Python import 代替。
- [ ] Runtime Server 的 `lingxi.advisor.search`/`lingxi.advisor.apply` 代表性调用通过；Operator 完成 preparation batch 创建、查询、
  结果读取，输出落所选 data root。联网/写动作使用受控 fixture repo 与数据。
- [ ] sampling 和 custom model 分别通过；缺少 Secret 时准确失败、补环境后恢复、token 轮换有效；
  config/state/log/Receipt/Agent 文件及 argv 均无测试 Secret。
- [ ] 完整仓库 CLI、独立 Delivery、实际 CodeHelix Plugin Management 各测；home 不存在、重装、升级、旧迁移、
  失败回滚、配置漂移、卸载保留数据均有证据。
- [ ] 移走开发 checkout、重启 Agent 后 MCP/Skill 仍可用，inspect/remove 同样不依赖 checkout。
- [ ] capability export 旧消费者契约回归通过；尚未实现的反向引用保护明确标注，不宣称 SWE-Pro 组合已验收。

`swe-pro-kit-with-lingxi-advisor` 的独立迁移/组合评测不在本期，不实现 EvalOrchestrator。
本次只更新文档与 Issue，未执行上述端到端功能验收。
