# LingxiAdvisor 独立 CodeHelix Plugin 改造说明

状态：历史设计记录，已由 Lingxi Advisor 0.2.0 实现取代。本文保留 0.1.x 的决策过程，
其中“只注册 Runtime”“模型配置必填”“预检索更新默认关闭”等结论不再是当前产品合同。
当前安装方式、完整 Runtime + Operator/Codify 工具面、模型回退与实际落点以
[README](README.md) 和 [验收记录](docs/acceptance.md) 为准。

基线快照（实施开始时必须重新核对，不能直接当作当前版本事实）：

- LingxiAdvisor 来源仓：`C:\Users\t84415073\Documents\GitHub\Lingxi-LingxiAdvisorGuidance`
- CodeHelix Plugin schemas：根描述符 `codehelix.plugin/v1`、target 声明
  `codehelix.plugin_target/v1`、生成的 Package manifest `codehelix.plugin_package/v1`
- CodeHelix Plugin Phase 1 实现基线：`34daf86`
- 首批计划验证基线：iCode / Chrys `0.20.1`、OpenCode `1.18.25`；它们是历史选定的基线候选，
  不代表已经完成本指南要求的四阶段真实验证，也不是天然的兼容范围上下界。

实现时还必须遵守仓库级 [Package 与 Delivery](../../docs/specifications/manifest-and-delivery.md)、
[本地 npx、安装协议与验证](../../docs/guides/installation-and-verification.md) 和
[测试与功能验收](../../docs/contributing/testing-and-acceptance.md)。本文只补充 LingxiAdvisor 特有决策；冲突时
以仓库级合同为准，并在同一提交中修正文档差异。

## 1. 最终要交付什么

建立一个独立的 `lingxi-advisor` Plugin，而不是继续从
`swe-pro-kit-with-lingxi-advisor` 中拆文件。两个 Plugin 并列存在：

| Plugin | 负责内容 | 不负责内容 |
| --- | --- | --- |
| `lingxi-advisor` | LingxiAdvisor Runtime Skill、Runtime MCP、私有 Python runtime、配置与知识数据位置 | SWE-Pro workflow、Lingxi 八个 Profile、Harbor runner、Chrys session metadata patch |
| `swe-pro-kit-with-lingxi-advisor` | 钉定的 SWE-Pro + LingxiAdvisor 组合形态 | 作为独立 LingxiAdvisor 的来源或自动依赖 |

首版独立 Plugin 只把 Runtime Profile 接入 Coding Agent，即只暴露：

```text
lingxi.advisor.search
lingxi.advisor.apply
```

LingxiAdvisor 来源仓中的 Operator Profile、Operator Skill 和六个 Codify Operation
工具继续保留，但首版不默认注册到 iCode 或 OpenCode。以后需要 Operator 时，在同一
Core 版本上增加显式安装选项；不要把 Operator 改成 Runtime 的超集。

## 2. 三层结构与责任

### 2.1 LingxiAdvisor Core module

它的外部 interface 是当前来源仓已经形成的 release bundle 和 Runtime MCP contract：

- 一个 `lingxi-advisor` wheel；
- `skills/lingxi-advisor/`；
- `packaging/runtime-server.json`；
- `lingxi-advisor-mcp --profile runtime --transport stdio`；
- Search → Apply 的最小输入输出 contract；
- LingxiAdvisor 自己的 Cache、Retrieval、Gate、Generation 与 Artifact Store。

不要为 CodeHelix 重写 Retrieval、Safety、Gate、Generation、XML schema 或 Artifact
identity。CodeHelix 也不应构造 LingxiAdvisor 内部 capability 对象。

### 2.2 CodeHelix Delivery / Package module

它的 interface 是：

- `codehelix-plugin.json`；
- 本地 npm bin：`codehelix-lingxi-advisor`；
- `check → plan → install → verify`；
- standalone 和 managed 两条入口共用一个 installer core。

Package 负责解释自己的 Skill、MCP、配置、凭据和目标适配。Plugin Management 只选择
Coding Agent、调用四个 operation、保存日志与 Receipt，不实现第二套 LingxiAdvisor 检查。

这里的 Package root 明确指 `plugins/lingxi-advisor/delivery/<target-profile>/`。Delivery root 是
**canonical Package root**，拥有 manifest、npm bin、installer core 与全部 payload；构建完成后
必须可以脱离仓库 checkout 独立安装。`plugins/lingxi-advisor/` 只是仓库内的 Plugin root，负责选择
Delivery，不是 Package root。

### 2.3 Plugin root 与仓库级 `plugin-kit`

LingxiAdvisor 不再复制一套根 CLI 和通用构建工具：

- `plugins/lingxi-advisor/bin/codehelix-plugin.js` 是薄 shim，只把 Plugin root 传给
  `plugin-kit/cli/plugin-cli.js`；因此 Plugin 根入口要求完整仓库 checkout；
- `build-delivery` 复用 `plugin-kit/build/delivery_build.py` 的 digest、copy 与 lock 原语；
- 构建时把 `plugin-kit/node/protocol-shim.js` 固化到各 Delivery；Delivery 运行时不得再读取
  仓库级 `plugin-kit/`。

仓库根 `npx . lingxi-advisor ...` 只委托给 Lingxi Advisor Plugin 根入口。仓库根、Plugin 根和
Plugin Management 都不能复制 LingxiAdvisor 的目标检查、安装或 verify 逻辑。

### 2.4 贡献者实现的 Coding Agent adapters

同一个 Plugin Source 生成两个 Delivery。目录名取决于门禁，不在实现前预设版本语义：

```text
plugin-kit/                         # 仓库级共享 CLI、protocol shim 与 build 原语
plugins/lingxi-advisor/
├── package.json                    # 仓库 checkout 内的人类入口
├── bin/codehelix-plugin.js         # 薄 shim
├── source/                         # 可维护 Source
├── build-delivery                  # Plugin 自己的薄构建入口
├── docs/
│   └── acceptance.md
└── delivery/
    ├── <icode-target-profile>/     # capability: icode-chrys；version: icode-chrys-0.20
    └── <opencode-target-profile>/  # capability: opencode；version: opencode-1.x
```

`source/` 可以保留 LingxiAdvisor 的原生结构；Delivery 必须是预生成、可直接安装的本地
npm Package。安装时不得读取同级 Source、访问来源仓、读取仓库级 `plugin-kit/` 或现场构建
LingxiAdvisor。

## 3. 利用现有 release bundle，不再手工复制源码

最新版来源仓已经提供：

```bash
uv run python scripts/build_release_bundle.py --output-dir dist
```

该构建会生成可复现 zip，内含 wheel、Skill、Runtime/Operator descriptor、安装器、
`bundle.json` 和 `CHECKSUMS.sha256`。CodeHelix 的 `build-delivery` 应：

1. 在固定来源提交上构建并解压 release bundle；
2. 将同一 bundle 分别固化为两个 Delivery 的 runtime payload，而不是让两个 Delivery 在运行时
   共享仓库内文件；
3. 加入贡献者实现的目标接入、target 声明和 Package installer，并从仓库级 `plugin-kit` 烘焙
   Node protocol shim；本仓不提供通用 Target Adapter；
4. 写入 `source-lock.json`，记录 `main@83ec684` 与 LingxiAdvisor `0.7.0`；
5. 生成 `delivery-lock.json`，覆盖全部预生成文件。

不要把来源仓的 `outputs/`、`knowl_cache/`、`lingxi-advisor_store/`、实验结果、`.env`、
`.venv` 或本地 repository/worktree cache 迁入 Delivery。现有 release builder 已排除这些
目录，新的构建不能绕开该过滤。

`plugins/lingxi-advisor/codehelix-plugin.json` 是 `active` 状态的 Plugin 根描述符；实现
沿用现有 `plugins/lingxi-advisor` 产品目录并补齐可安装结构。根描述符只保存逻辑身份和
target 索引，不是 LingxiAdvisor Core 的第二份 Loader contract。最终 Delivery manifest 必须由根描述符
与 `targets/*.json` 编译生成，不能人工复制 Plugin 身份。

Source、构建脚本或 adapter 发生变化后，必须重建两个 Delivery，并把 Source、Delivery、lock、
测试和文档放在同一提交序列中。不能手改 Delivery 后跳过可复现构建检查。

## 4. 两个 Delivery 的差异

下表描述目标能力和落地方式；标题不再暗示版本门禁。`0.20.1` 与 `1.18.25` 只作为首批真实
验证基线保留。

| 项目 | iCode / Chrys | OpenCode |
| --- | --- | --- |
| Skill | 安装到目标 config root 下的 Package 私有 Skill 目录，由新 Agent Profile 引用 | 安装到 OpenCode 原生 `config_root/skills/lingxi-advisor/` |
| MCP | 写入新 Chrys Agent Profile 的 `tools.mcp` | 写入 `opencode.jsonc` 的 `mcp.lingxi-advisor` |
| Agent Profile | 新建一个 LingxiAdvisor-enabled Code Profile | 不创建 Profile；OpenCode 原生 Skill + MCP 足够 |
| 源码修改 | 首版不需要 | 不需要 |
| Runtime | Package 私有 venv，安装预生成 wheel | Package 私有 venv，安装同一 wheel |
| 模型 | 首版按服务端模型配置 | 首版按服务端模型配置；不要假定 Host Sampling 可用 |
| Operator | 不注册 | 不注册 |

### 4.1 iCode / Chrys adapter

首批基线 Chrys `0.20.1` 已观察到 file Skill 与 Agent Profile 中的 stdio MCP 扩展点，因此
独立 LingxiAdvisor 不应照搬组合包的 Harbor runner overlay 或 session metadata patch。实施时必须
对真实目标重新探测这些能力，不能只根据版本字符串或路径存在性推断支持。

首版采用“新建 Profile”，不改用户已有 Profile：

1. 以目标实际安装的内置 `Code` Profile 为基准生成新 Profile；
2. 使用新的 `name`、`id` 和 `display_name`，不要 shadow 内置 `Code`；
3. 保留原 Code Profile 的模型继承和通用 Coding tools；
4. 在 `skills.paths` 加入 Package 安装后的 LingxiAdvisor Skill；
5. 在 `tools.mcp` 加入 `lingxi-advisor` stdio server，只允许 Search/Apply；
6. MCP command、runtime root 和 env-file 必须是安装后绝对路径。

来源仓 `skills/lingxi-advisor/agents/openai.yaml` 是 Skill 的展示/依赖元数据，不是 Chrys
Agent Profile，不能直接复制到 `~/.chrys/agents`。

如果实跑证明目标的 Profile/Skill/MCP interface 仍不足，不得让 capability-gated Delivery
静默降级为源码修改。应先记录证据、重新评审门禁与 surface，把最小源码修改声明为
`source-overlay` 并改用与该源码基线绑定的 version-gated Delivery；不能预先复制 SWE-Pro 的
patch。

### 4.2 OpenCode adapter

首批验证基线 OpenCode `1.18.25` 提供 Skill 目录与本地 MCP Server 接口；首版设计无需 JS/TS
hook Plugin。实施时仍要重新核对真实 CLI、配置 schema 与发现行为：

- Skill：`<config_root>/skills/lingxi-advisor/SKILL.md`
- MCP config：`<config_root>/opencode.jsonc`
- MCP name：`lingxi-advisor`
- MCP type：`local`
- command：绝对路径数组，启动 Package 私有 venv 中的 `lingxi-advisor-mcp`
- enabled：`true`

官方参考：

- [OpenCode Agent Skills](https://opencode.ai/docs/skills)
- [OpenCode MCP Servers](https://dev.opencode.ai/docs/mcp-servers/)

配置写入必须：

1. 保留 `opencode.jsonc` 中所有未知字段；
2. 首次修改前创建一次可辨识的备份；
3. 幂等更新 `mcp.lingxi-advisor`，不重复追加；
4. 使用 OpenCode 原生 Skill 路径，不依赖 `.claude/skills` 兼容目录；
5. 不把 token 或模型 key 明文写进 OpenCode config。

基线核查时 OpenCode MCP client 尚未启用 Sampling capability，因此不能把 Chrys 的 Host
Sampling 假设带到 OpenCode。实施时应重新核对官方文档与源码；在真实目标声明并通过 sampling
验收前，仍按“不支持”处理。历史核查参考：
[OpenCode MCP client source](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/mcp/index.ts)
和 [sampling feature issue](https://github.com/anomalyco/opencode/issues/11948)。
OpenCode 首版要完成 live search/generation，安装器应采集一个 OpenAI-compatible 服务端
模型配置，并映射为 LingxiAdvisor 的 Judge/Generator 环境变量。未来只有在目标版本真实
声明并通过 sampling 验收后，才能开放 Host Sampling 选项。

## 5. Runtime 目录与数据目录

两个 adapter 采用同一逻辑布局，根路径由各自 `config_root` 决定：

```text
<config_root>/lingxi/advisor/
├── runtime/                  解压后的 LingxiAdvisor bundle / install metadata
├── venv/                     Package 私有 Python 环境
├── config/runtime.env        GitHub 与模型 secret，POSIX 权限 0600
└── data/
    ├── knowl_cache/
    ├── cache/
    └── outputs/
```

MCP command 必须显式传入：

```text
--profile runtime
--transport stdio
--project-root <config_root>/lingxi/advisor/data
--env-file <config_root>/lingxi/advisor/config/runtime.env
```

不要依赖 OpenCode/Chrys 启动时的 cwd 推断数据位置。Plugin manifest 声明
`data_pointers` 指向 `target_config/lingxi/advisor/data/knowl_cache`，mode 为
`read_write`，这样 Guidance 数据页面只读取插件自己的真实数据位置；LingxiAdvisor 仍可在
没有 CodeHelix 的情况下独立运行。

## 6. Manifest 要表达的事实

两个 Delivery 的 `plugin.id` 都是 `lingxi-advisor`，Package bin 都是
`codehelix-lingxi-advisor`。Python distribution 和 MCP server name 保持为 `lingxi-advisor`。
Plugin 版本与 Core 版本分开：首版 Package 可从 `0.1.0` 开始，
`source-lock.json` 和 verify evidence 明确记录 Core `0.7.0`。

### 6.1 Components 与 surfaces

共同 `components`：

```text
skill        lingxi-advisor
mcp_server   lingxi-advisor-runtime (stdio)
```

iCode 额外声明：

```text
agent_profile  LingxiAdvisor-enabled Code Agent
```

OpenCode 不声明 Agent Profile、source patch 或 hook。

两个 manifest 都必须显式声明 `surfaces`，不能只靠 `components` 或
`requires.harness_features` 暗示落地方式。iCode Delivery 的首版功能依赖新 Profile 同时接入
Skill 与 MCP，因此 `agent_profile` 是 required，不是 optional：

```json
{
  "surfaces": {
    "skill":         { "required": true, "targets": { "icode": "native" } },
    "mcp_server":    { "required": true, "targets": { "icode": "native" } },
    "agent_profile": { "required": true, "targets": { "icode": "native" } }
  }
}
```

OpenCode Delivery 不创建 Profile，但应如实表达该差异：

```json
{
  "surfaces": {
    "skill":         { "required": true,  "targets": { "opencode": "native" } },
    "mcp_server":    { "required": true,  "targets": { "opencode": "native" } },
    "agent_profile": { "required": false, "targets": { "opencode": "unavailable" } }
  }
}
```

`components` 是 Package 资产清单，`requires.harness_features` 是宿主前置能力，`surfaces` 是组件面
是否必需及其目标落地方式；三者不能陈述互相冲突的事实。LingxiAdvisor 的 manifest contract 测试
必须交叉验证这一点。两个首版 Delivery 的 `installation.patches` 都应为空；若以后加入 patch，
必须同步修改 component、surface、plan 和 verify，而不是只在 installer 内部增加分支。

### 6.2 Compatibility gate

因为首版设计只使用原生 Skill、MCP、Profile/config，不修改目标源码，优先采用
`compatibility.gate: "capability"`。但只有在 `check` 能证明真实扩展能力时才允许这样命名；
只检查 `pyproject.toml`、`src/chrys` 或可执行文件路径存在，不足以构成能力探测。

最低探测要求：

- iCode：识别真实 Chrys checkout 与 config root；解析目标内置 `Code` Profile，验证生成 Profile
  所需字段及类型；验证 Skill 路径和 stdio MCP binding 的目标 schema；检查配置落点可用且没有
  所有权冲突；
- OpenCode：识别真实 CLI 与 config root；确认 Skill discovery 和 local MCP/config interface
  存在；能解析现有 JSONC 并证明未知字段可保留；检查配置落点和现有 `mcp.lingxi-advisor` 的所有权
  冲突；
- 两者都要在 `blocked` message 中点名缺失能力，不能退回“版本不支持”的笼统描述。

如果实施阶段无法在只读 `check` 中可靠完成上述探测，则该 Delivery 必须保留 version gate：

- capability gate 使用非版本化目录 `icode-chrys` / `opencode`；
- version gate 使用版本化目录 `icode-chrys-0.20` / `opencode-1.x`；
- 未知 `gate` 值必须 fail closed；缺省 `gate` 按 `"version"` 处理。

无论采用哪种 gate，都采集实际目标版本，并在 check/plan message、Package 安装记录和 CodeHelix
Receipt 中写入结构化 `target_version`。capability gate 下，manifest 的 `target_version` 只表示
已验证基线，不参与兼容判断；version gate 下才进行版本前缀匹配。

### 6.3 配置与 secret

共同配置：

- `issue_tracking_provider`：choice，当前默认并只正式支持 GitHub；
- `repository`：可选 `owner/repo`，留空时由运行任务按需提供；
- `GITHUB_TOKEN`：选择 GitHub 后必需，但安装阶段只检查存在与基本格式，不做在线认证；
- 多仓库预配置继续 hold，不在首版增加列表 schema；
- LingxiAdvisor model base URL；
- model name；
- model API key；installer 将同一组配置映射为 Judge 与 Generator 环境变量。

iCode 与 OpenCode 首版都使用服务端模型配置。Host Sampling 只有在普通 Profile 的 sampling
approval/binding 经过真实端到端验证后才作为可选 backend 加入。所有 secret 只进入
`runtime.env`，不得进入 argv、Registry、Receipt、plan 或日志。

## 7. Installer core

用户入口分三层，责任不同：

```bash
# 1. 完整仓库中的聚合入口
npx . lingxi-advisor install --list-targets

# 2. 完整仓库中的 Plugin 选择器
npx ./plugins/lingxi-advisor install
npx ./plugins/lingxi-advisor install \
  --agent <icode|opencode> \
  --target <coding-agent-root> \
  --config-root <coding-agent-config-root>

# 3. 完全脱离仓库 checkout 的 standalone Delivery Kit
npx --yes --package <delivery-root> codehelix-lingxi-advisor install \
  --target <coding-agent-root> \
  --config-root <coding-agent-config-root>
```

Plugin Management 直接调用 canonical Package root 的 managed protocol：

```bash
npx --package <delivery-root> codehelix-lingxi-advisor protocol <operation>
```

仓库根和 Plugin 根入口都需要完整 checkout；独立 Delivery Kit 只包含一个目标 adapter，必须
自包含，不读取 Plugin root、Source 或 `plugin-kit/`。Plugin 根入口选择目标 Delivery；Delivery
standalone 与 managed 共用以下 installer core：

1. `check`：按 manifest 的 gate 检查目标版本或实际能力，再检查 config root、runtime、必需配置、
   secret 是否存在及所有权冲突；不写文件；
2. `plan`：以 protocol 返回的 `changes` 为唯一变更真相，用中文列出 Skill、MCP、Profile/config、
   runtime 与数据位置；空 `changes` 必须如实展示为无变更，不能从 components 猜测；
3. `install`：验证 bundle checksum，创建私有 venv，安装 wheel，写 env-file，再调用目标 adapter；
4. `verify`：重新观察目标 post-state，不相信 install 返回码；返回实际安装 surfaces、版本和
   可审计 evidence。

交互安装使用 CodeHelix 现有的列表选择体验：预设可用 `↑↓` 移动，末行允许“自行输入…”。
不支持的 issue provider 即使通过自定义输入进入，也必须由 `check` 明确返回 `blocked`，不能
默默按 GitHub 继续。

冲突规则：同一 Coding Agent 已安装 `swe-pro-kit-with-lingxi-advisor` 时，独立 LingxiAdvisor 的
`check` 必须阻止覆盖相同 Skill/MCP/runtime 路径，并说明二者不可并装；不要静默接管组合包。
根入口从 Plugin 根描述符读取稳定身份，并按 target 声明定位多个 Delivery；Package 实例由 Plugin、
版本、agent system、harness 与 Delivery 路径决定，不能因为运行时探测到的 `target_version` 变化就
制造幽灵重复注册项。

## 8. Package 自检必须证明什么

### 8.1 共同检查

- 安装记录与 Package/Core 版本正确，并包含实际 `target_version` 与 `installed_surfaces`；
- bundle checksum 通过；
- 私有 Python 可 import `lingxi-advisor`，版本为 `0.7.0`；
- stdio MCP 可完成 `initialize → tools/list`；
- tools/list 严格等于 Search/Apply，不出现 Operator 工具；
- Skill 与 Delivery payload hash 一致；
- env-file 存在且日志、Receipt 不包含 secret；
- 数据目录可写，manifest/Receipt 能返回真实 data location；
- CodeHelix Receipt 的 `target_version` 与 Package 安装记录一致；目标版本无法读取时写空字符串并
  保留诊断 evidence，不能伪造 manifest 基线版本为实际版本；
- 重复安装幂等，不产生重复 MCP、Skill 或 Profile；
- 安装失败有 stderr 日志，目标不会被标记为已安装。

### 8.2 iCode 专项

- 在首批真实验证中记录 Chrys `0.20.1`；version gate 时还必须匹配 manifest 声明的 `0.20`
  前缀，capability gate 时只报告版本、不因前缀不同阻止安装；
- 新 Agent Profile 可由 Chrys Registry 加载；
- 原有用户 Profile 未修改；
- Profile 能发现 LingxiAdvisor Skill；
- Profile 中的 MCP command 使用安装后绝对路径；
- 安装前后 Chrys source checkout 的 tracked diff 不变；若以后确实增加 patch，此条改为验证
  manifest 声明的准确 post-state。

### 8.3 OpenCode 专项

- 在首批真实验证中记录 OpenCode `1.18.25`；version gate 时还必须匹配 manifest 声明的 `1`
  前缀，capability gate 时只报告版本、不因前缀不同阻止安装；
- `opencode debug skill` 能发现 `lingxi-advisor`；
- `opencode.jsonc` 的其他配置保持不变；
- `opencode mcp list` 或等价真实 probe 显示 `lingxi-advisor` 可连接；
- 真实 MCP tools/list 只包含 Search/Apply；
- 删除/损坏 command 时 verify 必须失败，不能仅因配置项存在就通过。

## 9. 功能验收：安装检查之外还要真实跑

验收证据分三层，不能互相冒充：

1. fixture/contract 测试证明 manifest、gate、surfaces、protocol 和异常分类的代码契约；
2. 真实目标安装验证在 Chrys/OpenCode 环境逐一执行 `check → plan → install → verify`，证明
   Package 确实装对；
3. Functional Acceptance 证明安装后的 LingxiAdvisor 确实参与 Coding Agent 的真实任务。

前两层通过不等于功能有效。Functional Acceptance 至少为 iCode 与 OpenCode 各运行少量真实案例：

1. 使用一个公开 GitHub 仓库与真实 issue description；
2. 第一次 `search(prepare_if_missing=true)` 真实执行 GitHub retrieval、Gate、Artifact
   生成与 `apply`；
3. 确认 Agent 后续模型调用实际消费 Apply content，而不是只调用了工具；
4. 第二次相同任务禁止重复 Generation，验证同一 Artifact ref/SHA、
   `cache_hit_count > 0`、`generated_count = 0`；
5. 再跑一个 `no_candidates` 或 runtime unavailable，确认 Coding Agent fail-open 继续任务；
6. 保留命令、Coding Agent 版本、session/run id、Artifact、日志和关键截图。

真实 GitHub 与模型链路不允许用 mock 代替。没配置外部凭据可以标记“未验证”，不能写成通过。

## 10. 来源仓基线快照中必须先复核的问题

以下结论只适用于 `main@83ec684` 的历史实跑，不得在未重跑的情况下继续称为“当前状态”。实施
开始时先核对来源 HEAD、Core 版本、release bundle 格式、测试结果与工作树；若问题已经修复，
在 acceptance 中记录新证据，而不是继续照抄旧数字。

### 10.1 macOS 进程树终止测试稳定失败

历史上在 `main@83ec684` 实跑：

```text
180 passed, 2 skipped, 1 failed
```

失败测试：

```text
tests/test_grounded_hardening.py::
GroundedHardeningTests::test_command_timeout_kills_child_after_wrapper_exits
```

单独复跑仍失败。直接原因位于
`src/lingxi-advisor/internal/command_runner.py::_terminate_process_tree`：POSIX 下 wrapper
已经退出时 `process.poll() is not None` 会提前 return，但继承同一 process group 和 pipe 的
child 仍在运行，最终写出 marker。本次发布使用审计 overlay 修复该提前返回，并增加跨平台可执行的
POSIX process-group 回归；macOS/Linux 实机进程树验收仍单独记录为未验证。

### 10.2 验收文档已落后

该快照的根目录 `VALIDATION.md` 仍写 V3 和 `141 passed, 1 skipped`，与当时 V4 代码和实跑结果
不符。
修复测试后应重新生成真实结果摘要；不要只改数字，也要区分自动测试、real GitHub/model
验收和跳过项。

### 10.3 本地锁目录不应污染交付状态

当时工作树有未跟踪 `knowl_cache/.locks/`。它不应进入 source snapshot 或 Delivery；应确认
运行结束后清理或由 `.gitignore` 排除，同时保留真正需要的并发锁语义测试。

## 11. 建议实施顺序

1. 重新核对来源仓与两个 Coding Agent 基线；修复仍存在的 release blocker，并更新
   `VALIDATION.md`；
2. 为两个目标编写只读能力 probe，先用真实目标裁决 capability gate 是否名副其实；不能证明时
   保持 version gate 和版本化目录；
3. 在 `plugins/lingxi-advisor` 补齐根描述符、薄根 shim、Source 与 `build-delivery`，复用
   仓库级 `plugin-kit`，不修改 LingxiAdvisor Core contract；
4. 先生成 OpenCode Delivery；它不需要 Profile/source patch，接入面更浅；建议随后真实验收；
5. 再生成 iCode Delivery 与新 Agent Profile；
6. 运行 `npx . build lingxi-advisor`、`npx . validate lingxi-advisor` 和仓库 fixture/contract 测试；
7. 建议运行 `npx . test-install lingxi-advisor ...`，再把每个 Delivery 复制到仓库外验证 standalone 与
   managed 四阶段，并分别跑一次真实功能闭环和降级；未执行时记录“未验证”；
8. 同批提交 Source、target 声明、两个 Delivery、lock、tests 和文档，并确认
   `npx . --list` 能发现 `lingxi-advisor`；真实证据有则一并提交。

## 12. 完成定义

- [x] 独立 `lingxi-advisor` Plugin 与 SWE-Pro 组合包无文件/安装路径冲突；
- [x] 仓库根与 Plugin 根 npx 能选择 iCode/OpenCode，并调用两个预生成 Delivery，不依赖
  CodeHelix 常驻；
- [x] 每个 Delivery root 都是自包含的 canonical Package root；复制到仓库外后仍可 standalone
  安装和运行 managed protocol，不读取 Source 或 `plugin-kit/`；
- [x] `components`、`requires.harness_features` 与 `surfaces` 无矛盾，iCode 的 required Profile
  不能被静默跳过；
- [x] gate 已由真实 probe 证明；capability gate 不做版本白名单，version gate 不伪装成能力探测；
- [x] 两个 Delivery 均支持 managed `check/plan/install/verify`；
- [x] iCode 使用新 Profile，不修改现有 Profile；
- [x] OpenCode 使用原生 Skill 与 MCP config，不修改 OpenCode 源码；
- [x] OpenCode live flow 不依赖未验证的 Host Sampling；
- [x] fixture/contract 通过；真实目标四阶段验证和功能验收若执行则分开记录，未执行则标为“未验证”；
- [ ] Package 安装记录与 CodeHelix Receipt 均保存实际 `target_version`，且不含 secret；
- [ ] 首次生成、第二次缓存复用和 fail-open 均有真实证据；
- [x] 来源仓测试全绿，跳过的 real integration 不计入通过；
- [ ] Plugin Management 和 Guidance 数据页面能读取 manifest/Receipt 中的真实安装与数据位置。
