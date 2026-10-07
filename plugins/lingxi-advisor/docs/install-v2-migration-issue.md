## 目标与状态

将 `lingxi-advisor 0.2.0` 接入共享安装 core，覆盖 Chrys/OpenCode、完整仓库 CLI、独立 Delivery 与 Plugin Management。
**框架正在实施、本插件尚未适配**。本期不开发 EvalOrchestrator/全局 dependency resolver，不改组合插件实现。

## 已核实的当前实现

- Chrys 0.20 / OpenCode 1.x 两 Target，版本门禁，无 Chrys 源码 Patch。
- 上游由 lingxi-advisor-extension-0.7.0.zip 与 import lock 固定。
- 两 Skill：lingxi-advisor、knowledge-preparation-operator；两 MCP Server 运行同一 lingxi-advisor-mcp 命令的 runtime/operator profile，**应共享一个 Python Runtime**。
- Chrys 有 LingxiAdvisor，OpenCode 缺此 Profile 是 optional surface。
- target config 的 lingxi/advisor 目前混合 release、venv、config/runtime.env、data、exports。
- 安装器将 token/key 写 runtime.env，并在安装时追加 Skill 内容；这两点与新存储合同冲突。
- 2026-09-15 `npx . validate lingxi-advisor` 通过（2 Targets/Deliveries）；此次未执行端到端 MCP/全仓 build 测试，不把历史合同问题当作已复现事实。

## 框架与贡献者待办

### 框架侧前置

- [ ] 同一 prepare/commit/inspect/remove、完整 PackageStore、Python Runtime、Skill symlink/copy、精确 ownership/回滚、状态/Receipt。
- [ ] 固定管理入口脱离 checkout 可用；Secret 不持久化，独立 Agent 启动有明确环境白名单合同。
- [ ] 明确固定 artifact 与传递依赖锁定的区别；不因 uv pip install 成功就宣称 dependency lock 已冻结。

### 插件贡献者

- [ ] build 生成自包含上游 MCP artifact；保留 import lock，Skill augmentation 移到 build，Store 安装后不改。
- [ ] 两 Target 声明 managed_install/v1：一个 Python runtime，真实可安装 source、已验证 python、command=lingxi-advisor-mcp；两 Server 共用 RuntimeRef。
- [ ] 从 request.managed 的 package_root/runtimes/config_ref/skill_activations 获取路径，不在 config 私建第二份 release/venv/state。
- [ ] 两 Skill 用框架 symlink/copy；target_paths 精确列出 Profile/MCP 配置/export，不登记整个 data root。
- [ ] **删除持久 Secret 设计**：不生成含值 runtime.env，不写 argv、Agent JSON/YAML、config/state/log/Receipt。
  保留 GITHUB_TOKEN 与 GITHUB_TOKEN_1…15 白名单/轮换；LINGXI_ADVISOR_MODEL_API_KEY 按实际模式要求。
- [ ] 非敏感 endpoint/model/allow-update/data-root 写部署配置；独立启动 Agent 时从其部署环境继承 Secret，不依赖安装进程，不读遗留 Secret 文件兜底。
- [ ] Chrys sampling 与 custom-model 模式分别实现/验证；OpenCode sampling 以实际客户端能力探测为准。
- [ ] Host Adapter 只处理 Profile/MCP/Skill/JSONC；保留无关 JSONC/注释。能力门禁区分 verified、预检查通过未验证、blocked，去掉无关目标 git drift 限制。
- [ ] 保留或显式升版 lingxi.advisor.runtime/v1 export，引用固定 launcher/Runtime/DataRef，不能遗留 env-file；operator 扩展须显式演进契约。
- [ ] 根据旧 ownership/import checksum 接管 release/venv/skills/注册/export；仅新部署验证后清理已知旧运行资产。
  知识缓存、preparation batch、outputs 保留原处或显式 data root。旧 Secret 不复制、不回显。
- [ ] 导出反向引用定义检查/迁移约束，不假设已有跨插件解析器或自动组合能力。

## 真实验收门禁

- [ ] validate/协议/安全合同、连续两次 clean build 通过并记录 artifact digest。
- [ ] Chrys 与 OpenCode 各真正加载两 Skill，并由各 Agent 真正唤醒两 MCP：initialize、tools/list、代表性调用。
- [ ] runtime 完成 lingxi.advisor.search/apply；operator 完成 preparation batch 创建、查询、结果读取，输出在指定 data root。
  写入/联网用受控测试 repo/data。
- [ ] sampling、custom-model、缺失 Secret、补环境恢复、token 轮换各有证据；扫描所有落盘配置/状态/日志及 argv 无测试 Secret。
- [ ] 三入口真实安装；无 home、重装、升级、legacy、配置 drift、失败回滚、卸载保留数据均测。
- [ ] 移走 checkout 后重启 Agent，MCP/Skill 与 inspect/remove 仍可用。
- [ ] 兼容 export 消费者回归，未完成的引用保护明确说明，不声称 SWE-Pro 组合已验收。

## 文档与范围

指南：`plugins/lingxi-advisor/docs/install-v2-migration.md`。
基线：`docs/specifications/plugin-installation-unification-overview.md`、`docs/specifications/installed-package-lifecycle.md`。
swe-pro-kit-with-lingxi-advisor 的独立迁移仅记录关联，不在此 Issue 修改或评测。
