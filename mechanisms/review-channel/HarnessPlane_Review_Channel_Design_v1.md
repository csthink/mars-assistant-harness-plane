# HarnessPlane 评审通道设计

> Depends on:
> `spec.md@r6 FR-21、FR-28、FR-37、FR-38、FR-40、FR-41、FR-50`
> `milestones.md@r12 gov-t8`
> `tasks/gov-t8/gov-t8.md`
> `HarnessPlane_Repo_Layout_Design_v1.md`
> `HarnessPlane_Delivery_Method_Design_v1.md`
> `task.template.md`
> `ruling.template.md`
> `HarnessPlane_Gates_Design_v1.md`
> `HarnessPlane_Handoff_Protocol_Design_v1.md`
> `D-09@r1`
>
> 权威状态: subject `review-channel`（治理记录目录按所在仓的布局规则解析；唯一状态正本）

CL-55 候选：拟修订 r9，语义级；原冻结基线 r8。本次仅起草，未送审、未 re-Freeze、未启用。完整变更集见 changelog/CL-55-review-evidence-local-archive.md；当前权威仍按 records/governance/review-channel/freeze-records.jsonl 解析。

最近已冻结基线（历史）：FROZEN r8，2026-09-08，CL-52 语义级变更集。Owner 已核差通过并授权共同 re-Freeze；冻结事实 = `records/governance/review-channel/freeze-records.jsonl` 内 revision 8 的记录。本次只冻结规则，历史读取与 HEAD 退出能力仍须完成 repo-layout §7.4 的施工与启用条件，不构成施工或删除授权。

前序冻结（历史）：FROZEN r7，2026-09-07，变更集 `changelog/CL-47-optional-governance-lint.md`。Owner 已核差通过、接受本次次序偏离，并授权本变更集 re-Freeze；冻结事实 = `records/governance/review-channel/freeze-records.jsonl` 内本次 `re-freeze` 记录。修改只覆盖 layout / manifest 可选化及直接消费者，原第 6 步范围不在本次展开。

前序冻结修订说明（历史）：本修订（FROZEN r6，2026-09-07）= Amendment 5，Changelog = `changelog/CL-45-artifact-templates-and-schema-retirement.md`；触发 = Owner 2026-09-07 裁定 J7 / J12（台账 `repo:OD-10`，减重第 5 步 5a）；前序 = Amendment 4（FROZEN r5，2026-09-06，`changelog/CL-44-review-channel-verdict-simplification-and-data-source-retirement.md`：判词契约五题闭集、轮次与处置流程、改动区、数据源退役四个面）。本修订为对齐级、语义零变化：task-artifact-schema 设计正本已随减重第 5 步退役，并与另三份工件 schema 设计正本合并为 `mechanisms/artifact-templates/` 模板集；本设计页首 `Depends on` 改指 `task.template.md` 与 `ruling.template.md`，正文对该正本各节的引用改为本设计自承载陈述（每轮四件最低成员与落点 §8.1、stage / round 闭集与任务轴单候选 §6.1 / §6.2、`bundle_manifest.json` 名）或改指对应模板（task record id 文法、`attempts/` 排除、`review-skip` ruling）；取值、闭集与失败码零变化，逐处 before / after 表见 Changelog 第 3 项。

## 1. Purpose

CL-60 已按 Owner 明确指令在本任务分支 re-Freeze r10，核差形态为 owner-review；冻结事实以 `records/governance/review-channel/freeze-records.jsonl` 内 revision 10 的记录为准。原始受审候选见 `records/diagnostics/assistant-hp/2026-09-21/candidate-map.json`；采纳时仅同步状态文字，逐字差异与正式身份见同目录 finalization-results.json 和 finalization-metadata.patch。下方前序候选与已冻结说明按形成时点作为历史读取。本次定稿不授权产品开工、真实模型调用或发布。

本仓自 2026-08-24 起的全部异源评审都借用创始档案库的评审通道（`AGENTS.md` §3 工具借用例外）。本设计在本仓重建受治理的异源评审通道，使 `spec.md@r6 FR-40`（唯一通道、跨模型提供方资格 fail-closed、评审结论结构机械校验、结论格式契约由通道注入）与 `FR-41`（每次 attempt 产出 Receipt、capability 凭 Receipt 演进登记、降级窗口内启动须 Owner formal 授权且随 Receipt 记录）在本仓机械成立，并退役对档案库通道的借用。

本设计同时承载 Owner 2026-09-01 就通道设计逐项作出的十七条裁定（`HANDOFF/ledger/gov-t8.jsonl` gov-t8:OD-02 其一至其十七，§10.1 逐条处置），`legacy:OD-15` 与 `legacy:OD-17` 两条台账行的复看结论（§10.2），以及创始档案库通道运行期间台账所记异源评审问题的结构性处置（§10.3）。

设计结果分四层：通道契约（§6）、评审方运行时适配层（§7）、落点与证据衔接（§8）、可执行物与自测（§5、§12）。契约层与适配层分离是本设计与档案库通道最大的形态差异：契约、Receipt 与判词不再出现任何单一调用工具的名词，调用工具与模型提供方接口都只是适配器。

## 2. 范围与邻接边界

### 2.1 本设计冻结

- 评审请求（Request）、被审输入与其清单、任务书生成、评审方指令注入与五题闭集、判词机读结构与信封包容规则、Receipt、attempt 分类闭集、跨模型提供方资格规则、Profile 选择与继承、轮次额度与加轮授权、capability 与 Registry 的文法与语义、逐条处置与决定文件（§6）。
- 评审方运行时适配层的接口与首批三类适配器的行为边界（§7）。
- 通道产物的落点派生规则、与 task record 每轮四件最低成员的对应（§8.1 自承载；原 task-artifact-schema §10，该正本已随减重第 5 步退役）、本地暂存层的构成（含决定文件）（§8；与 `locks` 门证据登记动作的衔接已随 Amendment 4 退役）。
- 单元内可执行物的模块划分、依赖方向与自测承诺（§5、§12）。
- 创始档案库通道借用形态的退役程序（§11）。

### 2.2 本设计不冻结、不吞占

- 评审证据的留存政策与耐久分级：产品要求由 spec FR-50 承载，物理留存由布局权威 §7 承载；CL-52 同批重开后，本设计 §8.5 规定历史轮读取及有条件的 HEAD 退出如何保持评审行为。CL-55 候选按同批上游 FR-50 调整新轮的本机耐久归档，具体执行契约见 §8.6；本通道不独立决定上游留存政策。
- 逐条核对与台账纪律的机械看守（`FR-38`）：本设计只使判词结构可被逐条核对消费（§6.5），看守本身归 gov-t11。
- Policy Gate 对轮次上限等约束的自动评估（`FR-28`）：本设计只在 Receipt 承载所需事实字段（§6.10），评估归 feature-t6。
- task record 目录成员闭集：本设计不新增任何 tracked evidence type；每轮四件最低成员的文件名由 §8.1 自承载（原沿 task-artifact-schema §10.2，取值零变化；task record 目录成员闭集自减重第 5 步起由 `task.template.md` 引导块承载）。
- Freeze Record 形制（gov-t5）、门运行日志（gov-t10）、中心 orchestrator（M-04）、非文本被审对象的评审面。
- 模型提供方或底层模型身份的密码学证明（档案库契约已接受的残留，本设计照录，§15）。

## 3. 术语与一处对照

本设计以 `spec.md@r6 FR-37` / `FR-41` 的既有用词为准，不使用隐喻表达（gov-t8:OD-02 其十二）。与上游其他正本用词的对照一次成文于此，正文不再另立同义词：

| 本设计用词 | 定义 | 上游或既有用词（同指） |
|---|---|---|
| 被审输入 | 一次 attempt 投递给评审方的全部材料：任务书、被审对象、参考件 | §8.1（原 task-artifact-schema §10.2）、`tasks/README.md`、档案库契约 §13 的「束 / bundle」 |
| 被审输入清单 | 被审输入逐件的来源路径、投递名、字节数、SHA-256、角色 | spec FR-37 的「bundle manifest」；§8.1 的 `bundle_manifest.json`（文件名为固定标识，原自 task-artifact-schema §10.2 继承，本设计不改） |
| 被审对象 | 被审输入中角色为 `candidate` 的每一件（一到多件，Amendment 2 多候选） | `task.template.md` 引导块的 candidate（原 task-artifact-schema §7.1） |
| 首候选 | 被审对象中位于评审请求 `inputs.candidates[0]` 的那件，即清单候选次序的首件；判词 `candidate` 字段所指对象，供只认单一候选身份的读端消费（freeze-record 设计 §8.1 读取约定） | 本设计定义（Amendment 2） |
| 改动区 | 通道对基线与本轮被审对象逐候选以 `difflib` 算出的差异块（hunk）集合，r1 基线 = 现行冻结事实字节、r2+ 基线 = 上一轮候选（§6.2 第 6 条、§6.3 第 3 节）；判词 `findings[].origin` 的 `changed_region` / `unchanged_region` 以之为判据 | 本设计定义（Amendment 4） |
| 决定文件 | Owner 对一轮判词逐条 finding 的处置决定的机读承载，`decisions.json`，由 `respond` 子命令写入本地暂存层（§6.12） | 本设计定义（Amendment 4） |
| 任务书 | 被审输入中角色为 `review-task` 的一件，由通道从 Request 渲染 | §8.1 的 Review Task Markdown（原 task-artifact-schema §10.2） |
| 判词 | 评审方对一次 attempt 的最终输出经通道校验后发布的文档，含机读块与叙述正文 | Verdict |
| 机读块 | 判词内唯一的 `review-channel-verdict` 围栏 JSON | 档案库 runner 设计 §13 的围栏 JSON 块 |
| 信封 | 机读块的围栏标记与其在判词内的位置形态，不含 JSON 本体 | 本设计定义 |
| Receipt | 每次 attempt 必产的技术凭据，`receipt-r<N>.json` | spec FR-41 的 Receipt |
| 评审请求 | caller 提交给通道的 JSON，`request_schema = review-channel-request/v4`（Amendment 4 换号；Amendment 2 自 v2 换 v3） | 档案库的 Request |
| 评审方运行时 | 实际驱动评审方模型完成一次评审的执行形态：调用工具进程或直接接口调用 | 档案库契约 §5 的 Runtime |
| 适配器 | 把一种评审方运行时接入通道的模块 | 本设计定义 |
| 调用工具 | 本机安装的 coding agent 命令行程序（如 codex、claude） | 档案库契约 §4.1 的 Caller 所用工具（注意：Caller 与评审方运行时是两个角色） |
| 模型提供方 | 被请求模型的声明厂商，如 DeepSeek、OpenAI、Anthropic、Zhipu | 档案库契约 §4.4 的 Reviewer Model Vendor |
| 路由提供方 | 接收请求的服务路由：官方接口、聚合商、调用工具内建后端 | 档案库契约 §4.3 的 Route Provider |
| Profile | 一次评审所需的完整可物化配置 | 档案库契约 §4.6 的 Review Profile |
| 轮 / attempt | 轮 = 有业务语义的评审轮次（`r<N>`，各 stage 自 r1 严格递增）；attempt = 一轮投递给一个 Profile 的一次技术尝试 | 档案库契约 §4.7（其 c 轮在本设计不存在） |

## 4. 设计目标：可维护性、中立性与质量

**可维护性是硬指标**（原 gates r13 设计 §3 的同一历史裁定，Owner 2026-08-25 以档案库 runner 2713 行加 selftest 2378 行为反例）。本设计把档案库单文件 runner 拆为职责单一的模块，并以下表把「改什么须动哪些文件」写成可验收的指标（§14 S9、S10）：

| 变更类型 | 允许的改动面 | 必须零改动的部分 |
|---|---|---|
| 新增一种评审方运行时 | 一个适配器模块 + 其自测声明 + Registry 内该 provider 条目（§5.2 数据驱动发现） | 契约层全部模块、契约常量、适配器接口模块、其余适配器、自测引擎 |
| 既有模型提供方下新增路由提供方或模型 | Registry 数据文件 | 任何 `.py`、设计正本 |
| 新增一个模型提供方（vendor） | 设计正本 §6.11 `vendors` 表（amendment）+ Registry 数据文件 | 任何 `.py` |
| 改判词机读字段 | 判词模块 + 指令注入的契约常量（同源）+ 自测声明 | 适配器、Receipt 组装、资格判定 |
| 改一条 Request 校验规则 | Request 模块 + 自测声明 | 其余全部 |
| 改轮次额度默认值 | Registry `defaults.max_rounds` 一个数字 | 任何 `.py` |
| 改五题闭集的题文（不改题号与题数） | 契约常量 + 自测声明 | 其余全部 |

**中立性是结构，不是声明**：契约层（§6）与产物（任务书、判词、Receipt、Registry 的能力字段）的 schema 不嵌入任何单一调用工具的专属结构（通用身份字段允许记录实际工具的取值，如 `runtime = codex-cli`、`tool = claude-code`）；调用工具专属知识（命令行参数、配置文件键名、事件流格式、stderr 关键词、认证文件路径）全部关在各自适配器内（§7）。本仓 Claude Code 与 Codex 会话都会写稿，跨模型提供方判定只看模型提供方（§6.8），任一写者提供方都存在合法异源评审方。

**结构化以提升质量为目的**（gov-t8:OD-02 其七）：判词机读字段的每一项都对应一条已登记的痛点或后继机械消费（§6.5 逐项注明），不为整齐而加字段。

## 5. 模块划分

### 5.1 扁平文件加命名前缀

布局权威 §5.1 单元目录文法的末槽是开放槽位（本节直接消费布局权威；原 gates r13 及其细目对该规则的转录现为历史，候选工具不另立目录语义）。本设计按 gov-t8:OD-02 其二把评审方运行时适配器放 `adapters/` 子目录（R28-B1 整改，Owner 2026-09-02 裁定恢复）；判定逻辑的其余模块取扁平文件加前缀 `review_channel_`（与 gates 单元同形态，属规模裁量而非上游约束）。**历史门缺口**（gov-t8:KB-02）：通道出生时 layout 对 hooks / fixtures 之外的子目录判红，严于布局权威；该历史不构成当前工具的限制，本候选按布局权威开放末槽核对。

```text
mechanisms/review-channel/
├── HarnessPlane_Review_Channel_Design_v1.md    # 本设计正本
├── review_channel.py                # 唯一入口：子命令解析、模块装配、退出码
├── review_channel_base.py           # 共享基座：错误类型、canonical JSON 与哈希、时间、原子发布原语、秘密扫描
├── review_channel_contract.py       # 契约常量：判词机读 schema、finding 与题号文法、叙述约定、分类闭集、失败码闭集（单一语义源）
├── review_channel_request.py        # 评审请求校验（对任意 JSON 全封闭）
├── review_channel_registry.py       # Registry 装载、schema 校验、capability 证据核验、defaults
├── review_channel_secrets.py        # 秘密来源：`~/.zshrc` 非执行解析、认证文件三态、扫描集构造
├── review_channel_inputs.py         # 被审输入：引用解析、封存、清单、禁名、缺件 fail-closed
├── review_channel_taskbook.py       # 任务书渲染（事实段由通道生成）
├── review_channel_instruction.py    # 评审方指令注入：判词契约文本 + 五题闭集（与判词模块同源常量）
├── review_channel_decisions.py      # 决定文件：校验、原子写入、r2+ 请求件派生段与残留项的派生与核对（§6.12）
├── review_channel_verdict.py        # 判词提取（信封包容三级）与机读块校验
├── review_channel_receipt.py        # Receipt 与 effective Profile 组装
├── review_channel_selection.py      # Profile 选择、继承、显式改选、跨模型提供方资格、轮次额度
├── review_channel_runtime.py        # 适配器接口、按 Registry runtime 值的数据驱动发现与装载、运行证据的统一形态
├── adapters/                        # 评审方运行时适配器（gov-t8:OD-02 其二）
│   ├── __init__.py                  # 空文件，只标记包；装载不依赖包导入（§5.2）
│   ├── codex.py                     # 适配器：codex 命令行
│   ├── claude.py                    # 适配器：claude 命令行（形态待施工期探针，§7.3）
│   ├── http.py                      # 适配器：直接接口（OpenAI 兼容 chat、OpenAI responses、Anthropic messages 三种协议）
│   └── <x>_selftest.py              # 各适配器的自测声明，一适配器一件
├── review_channel_registry.json     # Registry（活体数据文件，不入锁面，§6.11）
├── review_channel_selftest.py       # 自测引擎（只写一次）
├── review_channel_selftest_<模块>.py # 各模块的自测声明，一模块一件（适配器的住 adapters/<x>_selftest.py）
└── fixtures/                        # 自测数据：判词样本、Registry 样本、Receipt 样本、变异清单
```

### 5.2 依赖方向单向

```text
review_channel.py ──> 各契约模块 ──> review_channel_base.py
adapters/<x>.py ──> review_channel_runtime.py ──> review_channel_base.py
review_channel_selftest_<模块>.py · adapters/<x>_selftest.py ──> review_channel_selftest.py ──> review_channel_base.py
```

- 契约模块之间不互相导入；可共享的语义常量下沉到 `review_channel_contract.py`，可共享的机制下沉到基座；两者都不导入任何契约模块（R1-B11 整改：判词模块与指令注入模块经契约常量模块同源，不再互相导入）。
- 适配器只依赖适配器接口、契约常量与基座，不认识任何契约模块；契约模块不认识任何具体适配器（只经接口）。
- **适配器数据驱动发现**（R1-B11 整改）：适配器接口模块不含适配器名单。Registry `providers.<id>.runtime` 的取值 `<x>` 在装载时映射为单元内文件 `adapters/<x>.py`，以文件路径装载、装载模块名取 `review_channel_adapter_<x>`（净化启动下不依赖包导入，也避免与标准库同名模块如 `http` 冲突；`adapters/__init__.py` 只标记包）；文件不存在即 Registry 校验失败 `runtime-adapter-missing`。每个适配器模块导出固定属性：`RUNTIME_ID`（须等于去扩展名的文件名）、`SUPPORTED_KINDS`（kind 子集）、`SUPPORTED_TRANSPORTS`（transport 子集）、`run(...)`（§7.1 接口）；Registry 校验的 kind / transport 组合合法性由这两个属性判定，不在 Registry 模块内硬编码。新增一种评审方运行时因此只动三处：`adapters/<x>.py`、`adapters/<x>_selftest.py`、Registry 内引用它的 provider 条目（§14 S9 以机械 diff 验收）。自测引擎发现单元根 `review_channel_selftest_*.py` 与 `adapters/*_selftest.py` 两处声明。
- 仅 Python 3.12 标准库（gov-t8:OD-02 其二）；启动形态由本设计 §5.3 独立承载；运行时身份资格检查自 Amendment 4 起退役。

### 5.3 调用形态

本通道使用下列净化启动形态，解释器取仓库本地 `gates.interpreter`，不经 `PATH` 查找；该配置在本地 lint 钩子退役后仍是评审通道前置：

```text
"$(git config --get gates.interpreter)" -B -E -s -S -X pycache_prefix="$(mktemp -d)" \
  mechanisms/review-channel/review_channel.py <子命令> --request <评审请求绝对路径> [选项]
  mechanisms/review-channel/review_channel.py respond --decisions <决定输入绝对路径> [选项]
```

`respond` 只收 `--decisions`（§6.12），其余子命令只收 `--request`；两者都只收绝对路径。子命令闭集：`preflight`（零提供方接触）· `probe`（真实调用、只证 call-path）· `review`（正式评审；信封类与校验类两类补发均是其内部步骤，§6.5.4）· `respond`（写入并校验决定文件，零提供方接触，§6.12）· `selftest`。`register` 子命令自 Amendment 4 起退役（§8.4）。

**通道退出码由本节独立定义**，不表示 lint 的 PASS / VIOLATION / NOT_CHECKED 状态。净化启动保持上列形态，退出码按子命令与 attempt 分类唯一映射：

| 子命令 | `0` | `1` | `2` |
|---|---|---|---|
| `preflight` | 全部检查通过 | 任一检查拒绝（失败码在报告）或 `request-unrouteable` | 内部异常 |
| `probe` | `probe_completed` | attempt 分类为 `preflight_failed`（含调用前 `internal-error`）、`provider_unavailable`、`authentication_failed`、`runtime_rejected_config`、`timeout_or_transport_failure`、`cancelled_by_host`、`execution_port_failure`、`reviewer_output_invalid`（含调用后 `internal-error`）之一；或启动期 `request-unrouteable` | Receipt 写入自身失败 |
| `review` | `completed_with_valid_verdict`（判词为 PASS 或 FAIL 皆为 `0`，判定值在机读块与 Receipt；含经补发后校验 VALID 的情形） | 同 `probe` 的 `1` 列 | 同上 |
| `respond` | 决定文件校验通过并写入 | 校验拒绝（失败码 `decisions-invalid`，报告逐条列出不成立的规则）或判词不可定位 | 内部异常 |
| （补产 `interrupted`） | 不适用：该分类由后续 preflight 进程为已终止的 attempt 补产，不对应任何进程对该 attempt 的退出码；原 attempt 进程的结局是退出码 2（Receipt 写入自身失败）或被信号终止（无通道退出码） | | |
| `selftest` | 全绿含变异验收 | 任一红 | 引擎异常 |

通道自 Amendment 4 起不作运行时身份资格检查（Owner 2026-09-06 裁定 F9；原形态与四道门相同、复用 `records/runtime-environment.jsonl`，该文件自减重第 2 步起为只读历史档案且 gates 侧同款检查已于同步退役）；失败码 `runtime-identity-not-allowed` 退出闭集，任何子命令不再以退出码 2 拒绝解释器身份。

**CL-55 存储适用声明**：以下既有 request/v4、Receipt/v2、Registry/v3 是 legacy-git 接口；本候选新增 archive-v1 的 request/v5、Receipt/v3、Registry/v4，精确变更、旧读兼容及启用唯一见 §8.6。直到完成切换，现有工具仍按冻结旧接口运行；不能把文档候选当作实现支持。

## 6. 通道契约

### 6.1 评审请求

`request_schema = "review-channel-request/v4"`（Amendment 4 自 v3 换号：`review_brief.questions` 与 `standard_questions` 退出请求件属形状变更；Amendment 2 自 v2 换 v3 的依据是 `inputs.candidate` 单一路径改为 `inputs.candidates` 数组）。字段（校验对任意 JSON 类型全封闭，畸形形状一律成为有界失败并产 Receipt，档案库 runner 设计 §8.1 R3-B1 的继承）：

```text
subject                 必填，字符串，文法 ^[a-z0-9][a-z0-9-]*$；任务定义评审 = <task-record-id>-task，交付物评审 = 机制单元名
stage                   必填，闭集 task | impl（本设计自承载的闭集，原 task-artifact-schema §10.1；扩值须本设计 amendment 并同批更新 `task.template.md` 引导块的 `reviews/<stage>-r<N>/` 成员文法）
round                   必填，文法 ^r[1-9][0-9]*$（各 stage 自 r1 严格递增，本设计自承载，原 task-artifact-schema §10.1；本设计不设 c 轮，确认轮就是下一个 r 轮）
caller                  必填，非空字符串，UTF-8 不超过 256 bytes；外部 Host 使用稳定调用方标识（记录用，不参与任何判定）
task_record             可选，task record ID 文法（`TASK_RECORD_RE`，与 `task.template.md` 页首引导块同值：编号自 t0 起、不补零；原 task-artifact-schema §8.3）；在场即任务轴落点，缺席即 subject 轴落点（§8.1）
                        `review_channel_contract.py` 是该文法的唯一定义：`TASK_ID_RE` 为其 feature / design / gov 部分，
                        Domain Core 的来源核验复用同一常量，不另写文法
artifact_author         必填，{human_only: bool, authors: [{tool, model, vendor}]}；authors 每项三字段均为非空字符串，
                        tool = 产出方调用工具（如 claude-code、codex-cli、human），model = 精确模型标识（human 时取 "human"），
                        vendor = 模型提供方，须逐字命中 §6.11 `vendors` 闭集（大小写敏感，表外 fail closed）；
                        Human 项固定为 {tool: "human", model: "human", vendor: "human"}——`human` 是保留字、不属 vendors 表、不进派生集合（R6-B3 整改）；
                        tool = human ⇔ vendor = human（不一致即拒绝）；human_only = true ⇔ authors 全为 Human 项（且至少一项）；
                        通道派生 model_vendors = {authors[].vendor | tool ≠ human}，资格判定只用该集合（§6.8）
profile                 可选，{provider, model}（成对）；缺省按 §6.9 选择
effort                  可选，闭集 minimal | low | medium | high | xhigh
runtime_overrides       可选，dotted-key map；受保护前缀命中即拒（§7.2）
attempt_options         可选，{timeout_seconds}；不进 Profile、不被继承
inputs                  必填，{candidates: [路径], references: [路径]}（Amendment 2 多候选）：candidates 一到多件、数组内唯一、与 references 不相交，
                        次序即清单内候选次序（首候选 = candidates[0]）；task_record 在场（任务轴）时 candidates 恰一件——任务轮次 candidate role 恰一件，
                        §6.2 第 1 条自承载（原 task-artifact-schema §10.2 冻结、§10.3 禁本设计单方改变），多候选只适用于 subject 轴（R33-B1 整改）；通道自行计算清单，caller 不填哈希
review_brief            必填，人写段：{background, check_surfaces, evidence_limits: [{reference, reason, kind}],
                        accepted_residuals: [{id, text}], remediation_statement}
                        （Amendment 4：`questions` 退出，required question 集合为通道常量五题闭集，§6.4；caller 的关注点写 check_surfaces）；
                        accepted_residuals[].id 文法 ^RES-[1-9][0-9]*$、数组内唯一；r2+ 时须含上一轮决定文件 action = skip 项派生的残留项（§6.12）；
                        remediation_statement 在 r2+ 必填非空、r1 禁填；r2+ 时其开头须逐字等于通道自决定文件渲染的处置段（§6.12），其后可追加 caller 的整改叙述；
                        evidence_limits[].kind 可选，闭集 exemption | planned-location，缺省 exemption（R29-B2 整改；规定落点语义见 §6.2 第 2 条；
                        Amendment 2 / 3 增入的 locked-reference / archive-revision 两值自 Amendment 4 起退役，在场即请求文法失败），
                        表外值与缺 reference / reason 同属请求文法失败、preflight 拒绝；
                        evidence_limits[].reference 数组内唯一（R30-B1 整改）：同一引用出现多项即请求文法失败、preflight 拒绝
previous_round          r2+ 必填、**r1 禁填**（R23-B2 整改：与 remediation_statement 同款轮次约束；
                        r1 出现即 preflight 拒绝 `request-field-not-allowed`，该失败码随本次修正入闭集；
                        不再留「基线来源与失败结果均未定义」的缺口），
                        {verdict_path, receipt_path}；通道据此取上一轮机读块、Profile 与清单
max_rounds              可选，正整数；缺省取 Registry defaults
round_extensions        可选，[{authorized_by, at, added_rounds, note}]；Human 加轮授权记录（§6.10）
formal_review_authorized_by_owner   可选，JSON 布尔；capability 降级窗口内的正式评审须字面 true（§6.11 准入矩阵）
invocation_authorization            probe / review 必填，非空字符串，UTF-8 不超过 4096 bytes；本地治理调用写台账/裁定定位，外部Host写可信授权记录引用及范围说明；记录/散列而不解析决定编号，不从该文本获得权限
```

**最小可路由解析与 Receipt 总量性**（档案库 runner 设计 §8.1 的继承，本设计全文承载）：probe / review 模式在完整校验之前先做最小可路由解析——原始 JSON 可解析为对象，且 `task_record`（在场时）与 `subject`、`stage`、`round` 四者按各自文法可用；通过即派生 §8.1 的 `tracked_round_dir` 与 `attempt_round_dir`、分配 attempt_id，并**原子分配 attempt 目录**（R13-B1、R14-B2 整改）：在 `attempt_round_dir/.alloc-<attempt_id>-<pid>-<pid_start>/`（目录名内嵌所有者的 pid 与进程代际令牌，归属由名字判定、不依赖目录内文件）内写入 Request 原始字节的 exact copy `request.json` 与 `attempt.json`（下文「阶段状态记录」）并 fsync，随后一次 `os.rename(.alloc-… → <attempt_id>)` 入位——`attempt_round_dir/<attempt_id>/` 存在 ⇔ 两件完整在场；`.alloc-*` 遗留只在其名内所有者不存活时由 preflight 前置整体删除（所有者存活即不动）。分配之后才取同轮文件锁（§8.2 并发防线；锁按**一次 review/respond/recover 操作上下文**持有，在 finally 中释放；长寿命 worker 不等进程退出才释放；补发是 review attempt 内部的第二次调用、不是 attempt，不涉及新的取锁，gov-t8:OD-02 其十七）：锁被另一进程持有 → 本 attempt 以 `preflight_failed` + 失败码 `round-in-progress` 产 Receipt 结束（不是启动期失败）。**阶段状态记录 `attempt.json`**（R14-B3、R15-B2 整改）：随阶段推进每次以「临时文件 + 同目录 rename」原子重写，五态各携带截至该时点已确定的事实——`routed`：`{attempt_id, mode, pid, pid_start, at, phase, routing: {subject, stage, round, task_record, axis, tracked_round_dir, attempt_round_dir}, request_sha256, invocation_authorization_sha256, formal_review_authorized_by_owner}`；`sealed`：以上 + `effective_profile`（选定组必填，调用组与发布组 null；三组定义见 §6.6）、`input_manifest_sha256`、`round_budget`、`decisions_sha256`（r2+ 取上一轮决定文件字节的 SHA-256，r1 为 null，§6.12）、`delivery`；`calling`：以上 + `call_index`（首次调用 1、补发调用 2，§6.5.4；在发起外部调用**之前**写入，不含结果——调用是不可原子跨越的切点，崩溃于其间时记录停在此态）——补发的 `calling`（`call_index = 2`）记录形状 = 首次 `called` 记录 + `phase = calling` + `call_index = 2`，即另含已完成的 `effective_profile.calls[]` 恰首项与运行时组（R23-B1 整改）；`called`：以上 + `effective_profile.calls[]` 追加该次调用一项（累积、从不覆盖已记录项，R22-B2 整改）并由 `calls[]` 重算调用组三个归约字段（R24-B2 整改）、运行时组（首次 `called` 写入 `tool_version` / `api_endpoint_id`，补发的 `called` 只更新 `changed_within_attempt`，§6.6）、attempt 级 `call_path_proof` 与 `profile_binding` 的保守聚合值（§6.6；调用返回**之后**写入）——补发时 `calling` / `called` 以 `call_index = 2` 再各写一次；`validated`：以上 + `verdict_validation` 的实际值与 `extraction`（校验完成后、发布之前写入）。effective Profile 的发布组（`verdict_path` / `verdict_sha256`）只在 ⑥ 落位后正常写出的 Receipt 内取值，任何状态记录与补产 Receipt 内恒 null。补产 Receipt（§8.2 第 6 步）只读 `attempt.json`，其字段闭集按五态逐项列于 §6.6 补产行；`request.json` 只供审计与 `request_sha256` 复核，此后**包括 Request 完整校验在内**的任何 preflight 失败都原子发布 `classification = preflight_failed` 的 Receipt（失败码另记）。早期 Receipt 消毒：可能先于秘密解析存在的 Receipt 不逐字持久化自由文本——`subject` / `stage` / `round` / `task_record` 只在匹配文法时保留否则记 null，`invocation_authorization` 只记 SHA-256 摘要，失败说明为按失败码键控的静态消息；完整细节只进 stderr 报告。唯一无 Receipt 的失败 = **真正不可路由**：JSON 不可解析、非对象、或四个路由字段任一缺失或不合文法，任何 attempt 目录都无处存在，此时 stderr 事实报告 + 退出码 1，失败码 `request-unrouteable`。standalone `preflight` 不是 attempt，只输出结构化报告与退出码。校验对 JSON 标量语义同样封闭：要求整数处拒绝 JSON 布尔，`formal_review_authorized_by_owner` 只认字面 `true`。

与档案库 Request v1 的差异（继承对照原见 §10.4，该节已随 Amendment 4 退役）：`bundle.inputs` 逐件哈希改为通道计算（其一，任务书由通道生成，其六）；`review_questions` 字符串列表退役（r1 至 r4 曾改为 `review_brief.questions` 带题文；自 Amendment 4 起 required question 集合是通道常量，§6.4）；`artifact_author.model_vendors` 改为 `authors` 三元组列表（delivery-method §8 要求产出方的工具、模型与提供方身份机械可核）；新增 `stage`、`task_record`、`previous_round`、`max_rounds`、`round_extensions`、`accepted_residuals`、`remediation_statement`；`verdict_publish_path`、`inherit_from_verdict`、`reviewer_instruction` 三个字段退役——判词落点由 §8.1 派生，继承由 `previous_round` 承载，评审方指令由通道渲染不接受 caller 覆盖（覆盖通道等于绕开注入，档案库 r2 amendment 的教训）。

### 6.2 被审输入：构建、封存与清单

1. **角色闭集** = `review-task`（恰一件，通道生成）· `candidate`（subject 轴一到多件、任务轴恰一件，Amendment 2 多候选：每件各为一个被审对象，全部候选同束、同一判词逐件出身份；清单内候选次序 = 评审请求 `inputs.candidates` 次序；任务轴的恰一件由本条自承载（原 task-artifact-schema §10.2 冻结），R33-B1 整改）· `reference`（零到多件）。
2. **引用解析与缺件 fail-closed**（R1-B8 整改）：通道从**引用语法**出发提取被审对象内的候选引用，而非只识别现存路径。候选引用只取三类形态（R2-B7 整改，收窄）：其一，反引号内以仓根闭集成员起始的仓内相对路径——仓根闭集**不在通道内硬编码**，机械取自 `mechanisms/gates/rules_catalog.json` 的 `profiles.bootstrap.top_level_members.values` ∪ `profiles.bootstrap.root_tracked_members.values`（`layout` 门 `root-tracked-closure` 规则的同一数据源，布局权威 §4 / §8 的机器可读转录；R3-B4 整改），该文件不可读或缺该两键即 preflight 失败 `root-closure-unavailable`；其二，页首 `Depends on` 的裸文件名；其三，`<裸文件名>@rN` 形态。排除规则：围栏代码块内的内容不扫描；含 `<`、`>`、`*`、`…` 或 `<x>` 一类模板标记的串不是引用；含 `/v<数字>` 的 schema 标识、`~` 起始的用户路径、以 `.publishing-` 一类通道内部形态命名的串不是引用；以被审对象所在**单元目录**为前缀且仓内不存在的路径归为**计划交付文件**（在任务书「引用解析结果」节列出，不判缺件）。**比较算法**（R29-B3 整改明定；本设计 r1 的实现即如此）：单元目录 = 候选路径去掉基名后的完整目录路径（可为多段），判据 = 该路径以「单元目录加 `/`」为逐字节前缀；不取首段比较，故与单元目录仅共享首段、或目录名仅为单元目录名加后缀的兄弟目录之下的路径不在此列；候选位于仓根时无单元目录，本规则不适用。本规则是 r1 既有规则，本次修正不改其适用面；其用途 = 设计正本在施工前引用自身单元内尚未建立的交付文件（本设计 §5.1 的文件清单即例），放行面限定在被审对象自身的单元目录之内，该单元的交付文件是否建立由验收而非评审判定。**与规定落点的边界**（R29-B3 整改）：计划交付文件只覆盖被审对象自身单元目录之下的不存在路径，该单元目录因承载被审对象而必然存在；规定落点（本条下文）只覆盖首段所指顶层成员本身不存在的路径。同一路径不可能既位于一个已存在的单元目录之下、又以一个不存在的顶层成员起始，两条排除的适用面因此不相交，任一路径至多命中其一；单元目录之外、顶层成员已存在的任何不存在路径不走任一排除，判 `reference-unresolved`。**`D-<NN>@rN` 形态的明示排除**（Owner 2026-09-04 裁定「域四删」；自 R23-B1 起七轮的处置史见 CL-34 第 7 项）：公共 Decision 引用（形态 `D-<NN>@rN`，freeze-record 设计 §5.7 列举的直接上游引用之一）**不属本条三类候选引用形态**——它不是文件名（无扩展名），不进入提取集；通道对其不定位、不校验投递、不核对修订号、不判任何失败码，任务书「引用解析结果」节亦不列出它。该排除是明示的而非遗漏，理由三项：其一，本设计 r1 的提取规则本就不覆盖该形态（裸文件名判据要求名字含扩展名），本次修正对该形态的行为与 r1 相同；其二，其修订号的权威来源是 decision-mechanism 的治理流水完成事件（该机制 §4.5 / §5.2），该流水是散文、无机读结构，通道若解析即越界定义他机制的文法，若改取页首状态行则采信了仓级契约明定的非权威快照，故任何覆盖都须先由 decision-mechanism 提供机读接口，属其 amendment，本设计不预支；其三，只做定位与投递校验而不核对修订号的折中，须先改提取规则才能生效，属本次修正未登记的实现改动，且在 r27 至 r29 每轮各出一条 blocking。后果如实登记：缺失、拼错或已退役的 Decision 引用不触发失败码，由五题之 `Q-REFERENCE`（§6.4）交评审方人工核查。该形态的引用解析整体（提取、定位、投递校验、修订号核对）连同所需机读接口登记为后续设计输入（CL-34 第 8 项）。**规定落点**（本次新增）：被审对象是布局权威一类**定义目录结构**的文档时，其引用的落点是「规定应当有」而非「现在已有」——apps、ui、authority、.claude 一类按需目录（此处刻意不以反引号标注路径：本设计 r1 的提取规则会把它们收入引用集，而它们正是本条要排除的对象，标注即在本轮送审时自撞）在尚未建立时并不存在，通道若一律按现存对象解析即判 `reference-unresolved`，使这类文档无法送审（实测：布局权威正文有七处此类引用，逐一豁免则把机械校验退化为人工声明，且该文件每次修正都须重写）。故新增排除，**由 caller 显式声明、通道机械校验**（R28-B2 整改：仅凭「顶层成员当前不存在」无法区分「尚未建立的规定落点」与「顶层被误删或普通缺件」，自动放行会把三类情形一并放过）。形态（R29-B2 整改给出机械文法）：该引用须出现在 `review_brief.evidence_limits[]` 某项的 `reference`，且该项 `kind` 逐字等于 `planned-location`——`kind` 是 `evidence_limits[]` 项的可选成员，闭集 = `exemption`（缺省）| `planned-location`（§6.1；Amendment 2 / 3 增入的 `locked-reference` / `archive-revision` 两值自 Amendment 4 起退役，见本条末段），`reason` 仍是自由文本，只供任务书渲染、不参与任何判定；`kind` 缺省或为 `exemption` 的项不构成规定落点声明，按本条末段的豁免规则处置。声明成立与否由 `kind` 唯一决定；`evidence_limits[].reference` 在数组内唯一（§6.1；R30-B1 整改）。规定落点声明与豁免两条规则共用同一声明键（该引用的提取所得 token，裸名形态下为该 token 在选定域内解析所得的仓内相对路径），故一条引用至多命中其一，任务书对该引用的投递分类因此唯一（Amendment 2 / 3 的锁值引用件与档案库时代修订指称两条规则已随 Amendment 4 退役，本条末段）。通道对声明成立的项校验两项——其一，路径首段逐字命中仓根闭集（与其一同一数据源）；其二，该首段所指的顶层成员本身在仓内不存在。两项俱成立方归为规定落点，在任务书「引用解析结果」节按「声明为规定落点」列出、不判缺件；任一不成立则该声明无效，按原判据处置（首段成员已存在者即普通缺件，判 `reference-unresolved`）。声明因此不是豁免：它只免除缺件判定，不免除记录——任务书逐条列出声明与其校验结果，评审方据此判断该落点是否确属规定应有而尚未建立。**两项条件缺一不可**（R27-B2 整改：只取首段命中闭集会把任意缺件放行）——首段所指顶层成员**已存在**而其下路径不存在者，是普通缺件，仍判 `reference-unresolved`（例：机制区已存在，则其下某设计正本不存在仍判缺件；`records` 已存在，则其下某文件不存在同判）。首段不在闭集内的不存在路径同样仍判缺件。本排除因此只覆盖「该顶层落点整体尚未建立」这一情形，不构成对任意缺件的通用豁免。**解析域**（Amendment 1）：裸文件名引用的解析域由其形态与出现位置决定，通道先按形态取域、再在域内匹配，不做无条件全仓匹配——引用形态本身已携带对象类信息，freeze-record 设计 §5.7 的直接上游判定按同一分类取值（规划基线件裸名带 `@` 与修订号计其修订，裸文件名机制正本计其现行 FROZEN 修订，`D-<NN>@rN` 计 Decision），本设计 r1 对该信息未加利用，使同名的非规格链文件参与匹配。本次修正只消费前两类的对象类信息（域一、域二）；第三类的处置见本条「`D-<NN>@rN` 形态的明示排除」。**三域及其匹配集**（R1-B1 整改给出派生算法）：**域一** = 规格链目录（布局权威 §6.1 规定该目录承载规格链创始三件；顶层目录名 `sdd`），适用形态 = 规划基线件裸名带 `@` 与修订号后缀者，匹配集 = 受跟踪文件中路径恰为 `<域一目录名>/<裸名>` 者；**域二** = 机制区各单元目录（布局权威 §5；顶层目录名 `mechanisms`），适用形态 = 页首 `Depends on` 内的裸机制设计正本名，匹配集 = 受跟踪文件中路径恰为 `<域二目录名>/<单元名>/<裸名>` 者（`<单元名>` 为恰一层目录）；**域三** = 全仓，适用于其余裸文件名，匹配集 = 全部受跟踪文件中基名等于该裸名者。两个顶层目录名（域一、域二）须逐字命中 `mechanisms/gates/rules_catalog.json` 的 `profiles.bootstrap.top_level_members.values`（与仓根闭集同一数据源、同一读取失败处置）——任一不命中或该键不可读即 preflight 失败 `root-closure-unavailable`（两名 = 域一、域二的顶层目录名）；通道不硬编码目录路径字面量，域的语义归属由布局权威承载，本设计只消费其目录名并校验其在闭集内。**域一的现行修订号标注**（Amendment 4；Owner 裁定 F3 甲；台账 `repo-od-10:KB-08` 的闭合形态）：域一命中后通道**不核对**引用修订号是否在案：R2-B2 整改引入、经 R38-B1 至 R43-B1 六轮建立的在案修订号集合派生算法与其可信边界、Amendment 3 的档案库时代修订指称的声明放行整族自 Amendment 4 起退役，失败码 `reference-revision-unknown`、`archive-revision-unverifiable`、`archive-revision-not-archival`、`governance-records-unreadable` 退出闭集，通道不再以任何登记本作为治理判定数据源、不校验任何冻结记录的记录体（原文见 Git 历史，FROZEN r4）。退役理由：该核对拦下的唯一实例（CL-41 r1）是一个真实存在于出生档案库的修订，而其代价是六轮评审与整族可信边界；减重第 2 步后冻结记录改为 `freeze-records.jsonl` 一行形制、登记本转只读，该算法的数据源已冻结。**保留的唯一读取** = 现行修订号标注：投递的恒是现行字节；任务书「引用解析结果」节对每条域一引用并列标注引用修订号与投递字节的现行修订号，评审方据此判断该引用是否过时。现行修订号按 freeze-record 设计 §4.3 两条解析规则取值：读该 subject `records/governance/<subject>/freeze-records.jsonl` 内最后一行 `event` 非 `retire` 的 `revision`；该文件不存在时取该 subject 目录下编号最大的 `HarnessPlane_<Subject>_Freeze_Record_r<N>.md` 文件名后缀。subject 由引用路径反查，两步次序固定：先按 §4.3 其一，在各 subject（目录名字典序）的 `freeze-records.jsonl` 内取现行事实行，其 `objects[].path` 含该引用在域一解析所得的仓内相对路径者即为该 subject（首个命中即取；该路径位于现行事实行之后的 `retire` 行 `objects[]` 内时视为已退役、不可得）；jsonl 内零命中时按 §4.3 其二，对候选 subject 名（机制正本取其单元目录名，其余取文件名去扩展名；该 subject 已有 `freeze-records.jsonl` 者不回退）取编号最大的 `.md` 记录：记录带 `freeze-record` 围栏时其 `frozen_objects[]` 须含该路径（不含即非该件的记录，不取），雏形记录（无围栏）只取文件名后缀作修订号；两步均零命中即标注「现行修订号不可得」。标注只作事实、不判任何失败码；引用修订号写错不再被机械拦下，由五题之 `Q-REFERENCE`（§6.4）交评审方（§15 残留）。**存在性判定恒相对选定域**（R1-B1 整改）：选定域内零命中即 `reference-unresolved`，域外是否存在同名文件不改变该结论——域外同名件不是该引用形态所指的对象类；诊断层可在失败说明内列出域外同名命中，供 caller 判断是引用写错还是形态选错，该列举不参与任何判定。每个候选引用分别解析并分别 fail-closed：选定域内零命中 → `reference-unresolved`（拼错、被删、改名的正本，或引用形态与所指对象类不符）；选定域内多于一个命中 → `reference-ambiguous`——**不以 `inputs.references` 消解歧义**（R1-B2 整改）：参考件列表是 caller 可控输入，用它决定同一候选字节内裸引用的目标，等于把解析语义的决定权移交请求方，同一份候选换一份参考件列表即得不同解析结果；域内多命中恒拒绝，caller 应改用能由候选自身文本唯一解析的引用形态（带域前缀的仓内相对路径，或带修订号后缀的规划基线件裸名）；存在且唯一但未列入 `inputs.references` → `reference-missing`。三者任一命中即 preflight 拒绝，除非该引用出现在 `review_brief.evidence_limits[].reference` 且附 `reason`（该项 `kind` 缺省或为 `exemption`）——豁免只对仓外对象（如创始档案库文件）或上游明确允许不入的对象成立，仓内现存正本不得豁免。任务书把解析结果逐条渲染（已入 / 豁免及理由）。五题闭集之 `Q-REFERENCE`（§6.4）只是评审方视角的补充，不替代此处的机械拒绝。**多候选下的提取与判定**（Amendment 2）：候选引用自每个候选逐件提取，每条引用分别解析；引用所指路径是本束另一候选时按已投递处置（任务书记「候选之一」），是本候选自身时记「被审对象自身」；计划交付文件按各候选自身的单元目录逐候选判定。**锁值引用件（已退役，Amendment 4）**：Amendment 2 引入的 `kind = locked-reference` 形态（按 `records/lock-declarations.jsonl` 折叠所得 active lock 值引用受锁冻结件而不投递原文，调用前后各核一次字节）自 Amendment 4 起退役：该登记本自减重第 2 步起为只读历史档案（`records/README.md`），此后无任何 active lock 可核；失败码 `locked-reference-unlocked`、`locked-reference-mismatch`、`lock-declarations-unreadable` 退出闭集，指令注入不再含读取许可行，判词 `scope_files_read[]` 与 `findings[].location.file` 的允许集合收回为投递名集合（§6.5.2 第 9 / 10 条）。投递束瘦身改由「只审改动区」承载：任务书自 r1 起渲染改动区（第 6 条、§6.3 第 3 节），差异块之外的发现不得阻断（§6.5.2 第 14 条）。原文（三项校验、复核时点、实撞记述）见 Git 历史（FROZEN r4）。
3. **封存**：preflight 通过后，通道**先**把候选与参考件逐件复制进 attempt 目录、逐件 `cmp`、置只读，**然后**才从封存副本计算预清单、渲染任务书、计算最终清单（§6.3 次序）；封存后到评审结束期间任何来源文件变化不影响投递（复制件即输入），Receipt 与清单只记封存副本的值。这处置档案库 OD-158b 与 `tasks/README.md`「构建与送审之间不得改动」一类问题：改动不再造成失败，因为投递的是封存副本；但清单记录的是封存时刻，caller 若在封存后改了被审对象，判词对应的仍是封存字节，任务书由通道生成故不会写错哈希。
4. **投递名派生与禁名表**。**禁名表**：投递名不得为调用工具会隐式加载的指令文件名（`AGENTS.md`、`CLAUDE.md`、`CODEX.md`、`GEMINI.md`、`.codex`、.claude 目录、`.cursorrules`、`.rules`）；仓内同名文件投递时通道自动改名为 `source--<原名>`，不要求 caller 手改。**投递名派生：整束一次性全局唯一**（Amendment 1；R1-B5 整改）。去重面是**整束**，不是同基名组内局部。派生次序固定，结果确定：**第一步**，把固定名先置入**已占用集合**——任务书投递名（§8.1），以及本束实际生成的 `previous--` 族固定投递名（第 6 条复审四件）。预占集合按本束实际生成的固定名取，不写死数量。**第二步**，其余各件按来源路径字典序逐件派生：候选名初值 = 来源路径基名；命中禁名表则改为 `source--<原名>`；候选名与已占用集合冲突时，自末段起逐段向前扩展路径段前缀、段间以 `--` 连接，每扩展一段即重新比对已占用集合，取至不冲突为止；派生结果随即加入已占用集合。已占用集合含固定名与先前各件的最终投递名，故消歧对**整束全局**成立，而非仅对同基名组成立。**重复来源的前置去重**（R2-B4 整改）：派生之前先核对全部被审输入的来源路径两两不等（候选与参考件之间同样适用），重复即 `duplicate-reference-source` 拒绝（该失败码随本次修正入闭集）。同一来源路径因此不会进入派生流程——r1 规则把「同一来源重复列入」交给派生末端处置，而重复来源在逐段扩展下会各自得到不同名字并被放行，判据与宣称不符（R2-B4 实撞）。**保留前缀：集合、适用面与碰撞处置**（R2-B4 整改；R23-B4 闭合）。**集合**恰为两个串：`previous--`（第 6 条复审四件的固定投递名前缀）与 `source--`（本条禁名表改写前缀）；集合封闭，不含其他串。**适用面**（R24-B4 整改）：禁令约束**一切进入已占用集合的候选名**，含初始基名——r23 稿只约束逐段扩展结果，使本就名为 `previous--notes.md` 或 `source--notes.md` 的来源在无精确重名冲突时以初始基名直接通过，两个前缀因此未形成隔离命名空间。唯一例外是**禁名表动作实际生成**的 `source--<原名>`：该名由本条规则自身产生，不是来源自带的前缀，若一并禁止，根级禁名件（来源路径只有一段、无更多段可扩展）将无合法投递名可取。判别据此明确：名字以保留前缀起始且**非本次禁名表动作生成**者即受禁令约束——初始基名自带保留前缀时按冲突处置（进入逐段扩展），扩展结果自带保留前缀时同样处置。**碰撞处置**：逐段扩展所得名字若以保留前缀起始，继续扩展下一段；路径段取尽而所得名字仍以保留前缀起始，判 `bundle-name-collision`。两条断言因此不冲突（R27-B4 整改统一表述）：受禁令约束的是**一切进入已占用集合的候选名**，含初始基名与逐段扩展结果；**唯一不受约束的是禁名表动作自身生成的 `source--<原名>`**。根级禁名件改写后仍与已占用集合冲突且无更多路径段可扩展时，判 `bundle-name-collision`。**拼接不可逆的处置**：路径段自身可含 `--`，故不同来源路径的拼接结果可能相同（段序列 [`a--b`, `c`] 与 [`a`, `b--c`] 拼接同形）；逐段扩展取尽全部路径段后仍与已占用集合冲突即判 `bundle-name-collision`。该失败码自此只对「路径段取尽仍无法区分」成立——同一来源路径重复列入已由前置去重在更早处拒绝。**确定性**：同一束的同一组来源路径两次派生结果逐字节相同（次序由字典序固定，不依赖调用方给出的列表顺序）。清单 `inputs[].source` 保留完整来源路径，投递名到来源的反查由清单承载，不依赖派生规则本身。本设计 r1 的投递名恒取基名、冲突即 fail-closed，使候选正文引用两件同基名仓内文件时无法组束；该缺陷与第 2 条的裸名歧义出自同一触发事实（仓内存在同基名的多个文件），故同批处置。
5. **清单** = `bundle_manifest.json`（文件名固定，§8.1 自承载；原沿 task-artifact-schema §10.2）：`{subject, stage, round, task_file, inputs: [{source, bundle_name, bytes, sha256, role}], manifest_sha256}`，其中 `manifest_sha256 = sha256(canonical(inputs))`。**canonical JSON 编码**（R1-N3 整改，共享基座唯一定义，全部哈希与逐字节比较共用）：UTF-8、键按 Unicode 码点升序递归排序、分隔符 `,` 与 `:` 无空白、非 ASCII 字符不转义、整数不带前导零、字符串路径取仓内相对 POSIX 形态、无末尾换行。清单是 `FR-37` 所指「被审输入内容校验值」的承载物，入仓永久层。
6. **复审输入六项映射**（R1-B5 整改；原 task-artifact-schema §10.2 与档案库契约 §14 的全文承载，自减重第 5 步起本条即其唯一正本）。r2+ 时通道自动把下列固定投递名族加入被审输入（角色 `reference`，投递名固定前缀 `previous--`；件数 = 3 + 候选数，Amendment 2），并把另两项渲染进任务书：

| 契约 §14 六项 | 承载 | 来源 |
|---|---|---|
| 原被审快照 + 哈希 | 每个候选各一件 `previous--candidate-baseline--<该候选上一轮投递名>`（Amendment 2：逐候选取基线，以上一轮投递名区分；单候选同形，不另设单候选专名） | 上一轮清单所记每件 candidate SHA-256 对应字节：优先取 attempts 内封存副本，缺失时从 Git 历史取（`git show <引入提交>:<路径>`），两者皆无则 `baseline-unrecoverable` 拒绝；不做反向重建。本轮候选的来源路径集合须等于上一轮清单候选的来源路径集合，不等即 `inherit-unanchored`（候选集合在同一轮次序列内不变；增减成员即另起轴） |
| 上一轮不可变判词 + 哈希 | `previous--verdict.md` | `previous_round.verdict_path`，哈希与上一轮 Receipt 比对 |
| 上一轮清单与 Receipt（通道 identity） | `previous--bundle_manifest.json`、`previous--receipt.json` | 上一轮 tracked 目录；Receipt 同时入束用于通道 identity（本条自承载，原 task-artifact-schema §10.2） |
| 整改声明 | 任务书「整改声明」节 | `review_brief.remediation_statement` 原文（r2+ 必填；其开头为通道自上一轮决定文件渲染的处置段，§6.12） |
| 整改后快照 + 哈希与机器可核 delta | 任务书「改动区（通道算）」节 | 通道对基线与本轮被审对象计算统一差异统计与逐块摘要（改动区，r1 亦渲染，见本条下文） |
| 本轮 effective Profile | 任务书状态头「Profile」行 + Receipt | §6.9 选择结果，含是否换 Profile 及来源（显式 / 继承） |

**改动区与 r1 基线**（Amendment 4；Owner 裁定 F5；CL-34 第 8 项其三登记的缺口）：改动区 = 通道以 `difflib.SequenceMatcher` 对基线与本轮候选逐候选算出的差异块（hunk）集合，任务书第 3 节列每个 hunk 的基线行段与候选行段（既有形态）。r2+ 基线 = 上一轮候选（本表首行）。**r1 基线 = 现行冻结事实字节**：对每个候选，以其来源路径按第 2 条现行修订号标注的同一反查取该 subject 现行冻结事实内的身份（`freeze-records.jsonl` 行的 `objects[].sha256`；`.md` 记录取 `frozen_objects[].sha256`），再按本表首行的基线恢复算法（优先 attempts 内封存副本，缺失时按 `git log -- <路径>` 逐提交 `git show <commit>:<路径>` 取 SHA-256 命中的 blob）取得字节；该候选在任何 subject 的冻结事实内无身份（首冻）时任务书声明「整件为改动区」、不判失败码；现行冻结事实在案而其记录不含机械正本（雏形 `.md` 记录：修订号可得、`sha256` 不可得）时同样声明整件为改动区并注明该事实、不判失败码；身份（`sha256`）在案而字节不可恢复时 `baseline-unrecoverable` 拒绝（与 r2+ 同码）。r1 不加入 `previous--` 族投递名（无上一轮判词、清单与 Receipt）。改动区的判据止于差异块：`findings[].location.anchor` 是自由字符串，通道不能把一条 finding 映射到某个 hunk，`origin` 仍由评审方自报（§15 残留）。
7. **投递容量**：直接接口适配器（§7.4）以内联投递，通道以字节数与 Registry 该模型声明的 `max_input_bytes` 比对，超限即 preflight 失败 `input-capacity-exceeded`；调用工具适配器无此限（评审方自行读文件）。

### 6.3 任务书生成

任务书 = 通道渲染的确定性文档，caller 不再手写事实字段（gov-t8:OD-02 其一、其六；档案库台账第 1 类问题的处置）。渲染输入 = 评审请求、**预清单**（除任务书外每件被审输入**封存副本**的来源路径、投递名、字节数、SHA-256、角色）、上一轮判词机读块与 Registry；渲染后通道计算**最终清单** = 预清单 + 任务书条目，`manifest_sha256` 覆盖最终清单（R2-B4、R3-N1、R4-B4 整改：预清单从封存副本计算，任务书消费预清单、不消费含自身的最终清单）。同一输入两次渲染逐字节相同。结构固定：

1. **状态头**：subject、stage、round、授权引用、跨模型提供方判定结果（作者提供方集合、评审方提供方）、Profile、判词发布路径、通道标识（本仓通道及其设计修订）。
2. **对象与目标**：每个被审对象一行——投递名、字节数、SHA-256（通道算），按清单候选次序、首行即首候选（Amendment 2 多候选）；`review_brief.background` 原文。
3. **改动区、整改声明与决定摘要**（Amendment 4）：r1 只含「改动区（通道算）」小节：基线 = 现行冻结事实字节（基线修订号与 SHA-256 并列在场；首冻或记录不含机械正本时声明整件为改动区，§6.2 第 6 条）。r2+ 依次为「整改声明」（`review_brief.remediation_statement` 原文）→「改动区（通道算）」（基线 = 上一轮候选）→「上一轮决定摘要」（逐条 finding id、severity、title、action、instructions、work_item，来源 = 上一轮 `attempt_round_dir/decisions.json`，§6.12）→「上一轮 finding（须逐条处置）」（上一轮判词结论与机读块全部 finding，要求本轮逐条处置，§6.5）→ 本轮 Profile 与上一轮是否相同。改动区小节的内容 = 逐候选的 `difflib` 统一差异统计（增删行数）与逐块摘要（通道算；多候选下每候选一小节，按清单候选次序，Amendment 2），小节首句写明评审面默认只到差异块、差异块之外的发现取 `unchanged_region` 且不得阻断（§6.5.2 第 14 条）。
4. **核对面**：`review_brief.check_surfaces` 原文。
5. **证据面限制声明**：`review_brief.evidence_limits` 原文 + 通道追加的引用解析结果（哪些引用已入、哪些经豁免、哪些声明为规定落点；域一引用逐条并列引用修订号与投递字节的现行修订号，现行修订号不可得时如实标注（Amendment 4，§6.2 第 2 条）；Amendment 2 / 3 的锁值引用件与档案库时代修订指称两类自 Amendment 4 起不再出现）。
6. **已接受残留**：`review_brief.accepted_residuals` 逐条；评审方只确认不重报（档案库 OD-72b 的处置）。
7. **投递材料表**：由被审输入逐件渲染（角色、投递名、字节数、SHA-256 前 12 位）；**任务书自身一行只列角色与投递名，不列字节数与哈希**（R2-B4 整改：任务书的 identity 只由清单承载，任务书不自引用）。生成次序固定（R4-B4 整改）：封存候选与参考件（复制进 attempt 目录、置只读）→ 从封存副本计算预清单 → 渲染任务书并写入 attempt 目录 → 计算最终清单（含任务书条目）→ 调用。封存之后来源文件的任何变化都不影响投递与 identity；封存过程中逐件复制后 `cmp` 校验，不等即 `seal-mismatch` 拒绝。
8. **问题集**：该 stage 的五题闭集（§6.4），题号与题文由通道常量渲染、每轮相同；caller 的关注点只在第 4 节核对面。
9. **轮次额度状态**：本轮序号、生效额度、已用加轮、来源（§6.10）。
10. **授权与停止边界**：由授权引用与本仓固定文本渲染。

判词格式契约**不出现在任务书**，只由指令注入承载（`FR-40`「不依赖任务书手抄」）。任务书的发布生命周期见 §8.2（R1-N4 整改）：封存时先写入 attempt 目录作为投递副本，attempt 成功后随四件最低成员经 §8.2 提交协议一次 rename 进入 `tracked_round_dir`；attempt 失败时 `tracked_round_dir` 未被触碰（不存在）。

### 6.4 评审方指令注入与五题闭集

通道把下列内容确定性渲染为评审方指令，恒附加，不设豁免通道（档案库 runner 设计 §7 的继承）：

- 任务说明：读任务书，在被审输入内只读工作，最终消息即判词，不写文件；**差异块之外的发现 `origin` 取 `unchanged_region`**，且该类 finding 的 `severity` 不得为 `blocking`（Amendment 4；任务书第 3 节改动区为判据，§6.5.2 第 14 条）。
- **判词契约文本**：机读块形态与全部字段（与 §6.5 校验器同一常量渲染）、finding 编号文法、`assessment` 闭集、PASS 与 blocking 的互斥、上一轮 finding 逐条处置义务、题号精确等集、raw HTML 禁令。**「全部字段」的机械判据**（Amendment 1；R1-B4 整改给出文法）：**字段行** = 注入文本内以 `- ` 起始、其后至首个 `:` 之间为字段名位的行；**字段名位** = 该行 `- ` 之后至首个 `:` 之前的字节序列，去首尾空白后须逐字等于字段名。**完整映射**：§6.5.1 机读块字段表内的每个字段各恰有一条字段行——`verdict_schema`、`verdict`、`human_decision_required`、`subject`、`stage`、`round`、`candidate`、`candidates`（Amendment 2）、`question_assessments`、`findings`、`previous_findings_disposition`、`accepted_residuals_acknowledged`、`scope_files_read`、`tools_used`、`authorization_disclaimer`，其中 `previous_findings_disposition` 在 r1 与 r2+ 均须在场（r1 的字段行说明其取空数组）。**组合字段**：§6.5.1 表内合并列出的 `subject / stage / round` 按成员各占一条字段行，不得合并为一行。**嵌套必填成员**（R2-B3 整改）：嵌套成员不以自由散文承载，否则删除其说明后判据仍判绿、「全部字段」的失败类未被封住。形态 = 其所属字段行内含一个由 `{` 与 `}` 界定、以 `,` 分隔的成员名序列；成员自身带必填子成员时以 `<成员名>{<子成员名序列>}` 表达，**递归至 §6.5.1 声明的最深层**（R23-B3 整改：单层序列无法无歧义表达嵌套对象，`findings[].location` 的 `file` / `anchor` 因此漏检——缺其一的判词仍可满足单层判据）。校验对每个带嵌套必填成员的顶层字段——`candidate`、`candidates`、`question_assessments`、`findings`、`previous_findings_disposition`——逐层核对其成员名集合**恰等于** §6.5.1 所列集合，缺失或多出即判红；删除任一层的任一成员说明即在此失配。成员名序列之外的行内文本（取值域、约束说明）不受本判据约束。**校验形态**：对渲染后的注入文本，按上列字段名集合逐一核对字段行存在且恰一条，缺失或重复即判红。实撞：`verdict_schema` 在 r1 实现中只出现于字段清单的标题句内，评审方漏写该字段，判词被 §6.5 判 INVALID，而该情形不属 §6.5.3 三级的不可解析、不进补发轮，该轮作废。本判据属 §12 自测承诺覆盖面。
- **机读块位置要求：判词以机读块开头，叙述正文在后**。理由：输出被截断时坏掉的是叙述而不是 JSON（gov-t8:OD-02 其八「待考虑」项，本设计采纳）。提取接受任意位置（§6.5.3），发布文档恒把机读块规范化到开头。
- **叙述正文的机械可恢复约定**（R1-B6 整改，为补发轮的不变性核对提供独立来源）：正文首行 `**Verdict: PASS|FAIL**`，第二行 `**Human decision required: yes|no**`；每条 finding 一个标题级小节，标题形态 `### <id> · <severity> · <title>`（severity 取 blocking / non_blocking / human 三值）；一个 `## Question assessments` 节，每题一行 `- <question_id>: SATISFIED|NOT_SATISFIED|INDETERMINATE`（Amendment 4 去 `· exhaustive: true|false` 尾段）；r2+ 一个 `## Previous findings` 节，每条一行 `- <prev-id>: RESOLVED|UNRESOLVED|INDETERMINATE`。这些行是注入要求也是校验项：与机读块不一致即 INVALID（§6.5.2 第 13 条）。**叙述骨架注入**（Amendment 2；台账 repo-od-09:KB-02 其二）：上列约定不再只以规则描述注入，通道把它渲染为**逐行填空的叙述骨架**并恒附加——固定行序、节名与标点逐字给出，取值位以尖括号占位：第 1 行 `**Verdict: <PASS|FAIL>**`、第 2 行 `**Human decision required: <yes|no>**`、finding 小节模板行 `### <ROUND>-<B|N|H><n> · <blocking|non_blocking|human> · <title>`（`<ROUND>` 以本轮轮号的大写字面渲染）、`## Question assessments` 节下**每个 required question id 各一行**（题号逐字渲染、取值位占位）、r2+ 的 `## Previous findings` 节下**上一轮每条 finding id 各一行**（id 逐字渲染、取值位占位）。**骨架行判据**（机械，属 §12 自测承诺覆盖面）：注入文本内须逐字含上列各行——两条首行、模板行、两个节名行（r1 只一个）、每个 required question id 与上一轮 finding id 各恰一行；缺失或重复即判红。**同源渲染**：骨架由契约常量的同一渲染函数产生，以占位值渲染即注入骨架，以机读块实际值渲染即校验类补发的骨架（§6.5.4）；自测断言**往返性质**——对任一有效机读块，以其值渲染骨架所得叙述经 §6.5.2 第 13 条恢复后与该机读块逐项相等。实撞：CL-39 变更集 r2 两轴首次投递均因叙述排版漂移（标题形态、节名、全角冒号、物理第 2 行）判 `reviewer_output_invalid`，而同一 Profile 同日 r1 两轴排版合规，属输出随机漂移而非规则不明；骨架压缩漂移空间，契约本身不放宽——叙述与机读块一致仍是防「机器读的结论与人读的结论不同」的必要规则。
- **五题闭集**（Amendment 4；Owner 裁定 F1 / F2；取代 r1 至 r4 的「caller 自由题 ∪ 常设问题集三题」）：required question 集合是通道常量，按 stage 取套，caller 不再提交题目（`review_brief.questions` 自 `review-channel-request/v4` 退出；`standard_questions` 开关与 `STD-` 前缀题随之退役）；题面每轮相同，评审方对题面本身不开 finding。id 文法 `^Q-[A-Z]+$`，与旧 `Q<n>` / `STD-<n>` 不相交，旧判词按 `verdict_schema` 区分。两套题表如下；两套的题号集合各恰五个、互不相交（`Q-BOUNDARY` 在两套内题文不同，按 stage 取义）；注入文本内每题一行、题号与题文由与校验器同源的常量渲染，叙述骨架的 `## Question assessments` 节按该套逐题渲染占位行。

**task 轮**（Review Definition；逐字承接 `spec.md@r6 FR-21` 的五维度）：

| id | 题 |
|---|---|
| `Q-FIDELITY` | Fidelity：Definition 是否忠实于上游任务名单项与 spec 条目 |
| `Q-GOAL` | Goal Soundness：目标是否成立、可达 |
| `Q-BOUNDARY` | Boundary：范围边界是否清楚，未越出名单项 |
| `Q-ACCEPT` | Acceptability：Acceptance Criteria 是否可判定 |
| `Q-EXEC` | Executability：按 Definition 能否施工 |

**impl 轮**（设计正本、变更集、实现）：

| id | 题 | 来源 |
|---|---|---|
| `Q-CHANGE` | 改动区正确性：差异块内的改动是否正确、完整地实现触发事实（Changelog / Definition） | Amendment 4 新增（承 FR-21 Fidelity 于 impl 面） |
| `Q-UPSTREAM` | 上游一致：改动与上游冻结件、既有 Owner 裁定不冲突，被审对象自设的规则成立 | 原 `STD-2`（档案库 KB-39b 的处置） |
| `Q-PREMISE` | 前提与起点完备：被审对象所依赖的前置对象、起点步骤是否齐备 | 原 `STD-1`（档案库 OD-64 的处置） |
| `Q-REFERENCE` | 引用可解析：被审对象内每处引用在被审输入内可定位或被证据面限制声明覆盖；域一引用的修订号与任务书并列标注的现行修订号是否相符 | 原 `STD-3`（档案库 OD-138b / KB-30 的处置；Amendment 4 起同时承接已退役的域一修订号核对） |
| `Q-BOUNDARY` | 边界与残留：改动面未越出触发事实；差异块之外的发现只以 unchanged_region 报出 | Amendment 4 新增（承交付方法 §7.6 边界条） |

### 6.5 判词契约

#### 6.5.1 机读块字段（`verdict_schema = "review-channel-verdict/v4"`；Amendment 4 自 v3 换号：`question_assessments[]` 成员减少；Amendment 2 自 v2 换 v3：新增必填字段 `candidates`）

```text
verdict_schema             固定 "review-channel-verdict/v4"
verdict                    "PASS" | "FAIL"
human_decision_required    bool；恒等于「存在 severity = human 的 finding」
subject / stage / round    与评审请求逐字相等
candidate                  {bundle_name, sha256}：首候选身份（清单候选次序首件），须与清单相等；恒等于 candidates[0]
                           （Amendment 2 保留该字段，供只认单一候选身份的读端：freeze-record 设计 §8.1 读取约定）
candidates[]               [{bundle_name, sha256}, ...]：全部被审对象身份的精确等集，次序按清单候选次序（Amendment 2 多候选）
question_assessments[]     {question_id, assessment: SATISFIED | NOT_SATISFIED | INDETERMINATE,
                            evidence_refs[], finding_ids[]}（Amendment 4 去 exhaustive / exhaustiveness_note；
                            题号集合 = 该 stage 的五题闭集，§6.4）
findings[]                 {id, severity: blocking | non_blocking | human, title,
                            location: {file, anchor}（file ∈ 投递名集合，§6.5.2 第 10 条），
                            origin: changed_region | unchanged_region | introduced_by_remediation | carried_over, summary}
                           （origin = unchanged_region ⇒ severity ∈ {non_blocking, human}，§6.5.2 第 14 条，Amendment 4）
previous_findings_disposition[]   r2+ 必填：{id, disposition: RESOLVED | UNRESOLVED | INDETERMINATE, evidence_refs[]}
accepted_residuals_acknowledged[] 评审请求所列残留 id 的精确等集（r2+ 时含上一轮决定文件 skip 项派生的残留，§6.12）
scope_files_read[]         被审输入投递名子集（§6.5.2 第 9 条），含任务书
tools_used[]               调用工具路径下非空；内联投递下必须为空数组（Receipt `delivery` 记录投递形态，§6.5.2 第 9 条为唯一规范定义）
authorization_disclaimer   固定 true
```

每个字段对应的痛点或消费方（§4 第三条承诺）：

| 字段 | 对应 |
|---|---|
| `findings[].location` | gov-t11 逐条核对（`FR-38`）须机械定位；档案库 OD-138b「引用图中不存在的节点」的处置 |
| `findings[].severity = human` | HUMAN 裁决点从散文升为字段，caller 停报判据机械可取（档案库 OD-127） |
| `findings[].origin` | `legacy:OD-15` 成因统计：整改自伤（`introduced_by_remediation`）、未改动区新面（`unchanged_region`）可按轮次机械计数；自 Amendment 4 起另为阻断资格判据（§6.5.2 第 14 条：`unchanged_region` 不得阻断，Owner 裁定 B 的 finding 级承载） |
| `previous_findings_disposition` | `FR-38`「上一轮每条 finding 在本轮被显式处置」的判词侧承载；档案库契约 §14 的继承 |
| `accepted_residuals_acknowledged` | 已接受残留不被重报（档案库 OD-72b） |
| `candidate` | 判词与首候选身份的自报绑定，读端与清单比对；freeze-record 设计 §8.1 读取约定所消费的字段 |
| `candidates` | 多候选束内判词对全部被审对象的身份绑定；freeze-record 设计 §5.3 C1 消费清单候选集合，本字段是判词侧对同一集合的自报（Amendment 2） |

`blocking_finding_ids` 与 `non_blocking_finding_ids` 两个数组退役，由 `findings[].severity` 派生；档案库判词 v1 的语义规则全部保留并改写到新字段上（§6.5.2）。

#### 6.5.2 机械校验规则（任一不符即 `verdict_validation = INVALID`）

1. `PASS` ⇔ 无 `blocking` finding；`FAIL` ⇔ 至少一条 `blocking`。`human_decision_required` ⇔ 存在 `severity = human` 的 finding（机读块与 Receipt 同值）；为 true 时 caller 恒停报，无论 PASS / FAIL。
2. `question_assessments` 的题号多重集 = 评审请求 `stage` 对应的五题闭集（§6.4 常量），精确等集且每个题号恰一条 assessment（缺题、多题或重复题号即 INVALID；Amendment 4）。缺题或多题的修复要求评审方新增或删除一条 assessment，属判断字段缺陷、不补发（本节末段、§13 N）。
3. `PASS` 要求每题 `SATISFIED`，或 `INDETERMINATE` 且其 `finding_ids` 只引用 `severity = human` 的 finding（R2-B5 整改：待 Human 裁决的题不表述为已满足，也不制造虚假 blocking）；非 `SATISFIED` 的题必须引用至少一条 finding。
4. finding 引用双向闭合：assessment 引用的 finding 必须已声明；每条 finding 至少被一题引用。
5. finding id 文法 `<ROUND>-B<n>` / `<ROUND>-N<n>` / `<ROUND>-H<n>`，全局唯一，三类各自从 1 连续，前缀字母与 `severity` 一一对应（B = blocking、N = non_blocking、H = human，不符即 INVALID）；每条 finding 在叙述正文有标题级小节（围栏内标题不计）。
6. r2+ 时 `previous_findings_disposition` 的 id 多重集 = 上一轮机读块 finding id 集合的精确等集，每个 id 恰一条（重复即 INVALID）。
7. `accepted_residuals_acknowledged` = 评审请求残留 id 的精确等集，无重复。
8. `candidate.sha256` = 清单首候选的 SHA-256 且 `candidate.bundle_name` = 其投递名；`candidates[]` 的 (bundle_name, sha256) 对序列 = 清单全部 candidate 项按清单候选次序的序列（同成员、同次序、无重复；R32-B2 整改明定为逐项同序相等），由此 `candidates[0]` 恒等于 `candidate`（Amendment 2）。
9. `scope_files_read` ⊆ 投递名集合（Amendment 2 曾并入锁值引用件路径集合，Amendment 4 收回），且含任务书；`tools_used` 在调用工具适配器下非空、在直接接口的内联投递下必须为空数组（Receipt `delivery = inline` 记录投递形态，评审方无工具）；`authorization_disclaimer` 为 true。
10. `location.file` ∈ 投递名集合（Amendment 4 收回锁值引用件路径集合）。
11. 秘密扫描命中即 INVALID（§7.5）。
12. 校验器对任意 JSON 形状全封闭，自身异常折算 INVALID 并保全诊断层。
13. 叙述正文按 §6.4 约定机械恢复的 verdict、finding（id、severity、title）、逐题 assessment、上一轮 finding 处置，与机读块逐项相等；不一致即 INVALID。
14. **未改动区不阻断**（Amendment 4；Owner 裁定 B「保留阻断但分档」的 finding 级承载，裁定 F4 甲）：`origin = unchanged_region` 的 finding 其 `severity` ∈ {`non_blocking`, `human`}；取 `blocking` 即 INVALID，`verdict_problems[]` 记以 `rule-14:<finding-id>` 起始的一项。该失败属判断字段缺陷、不补发（本节末段）：attempt 分类 `reviewer_output_invalid`、失败码 `verdict-invalid`，不产生 tracked Receipt、不计入轮次额度（§6.10），caller 按 §6.7 规则 7 归因后**原样重投同一轮**（请求件一字不改）。`changed_region`、`introduced_by_remediation`、`carried_over` 三类不受本条限制。severity 闭集不变，不新增字段；对象级的分档（哪类对象默认开评审）归交付方法 §8 矩阵，本设计不第二次定义。

叙述正文中、已闭合代码围栏之外，任何以 `<` 后接字母、`!`、`/` 或 `?` 开头（允许至多三空格缩进）的行即 INVALID：raw HTML 整类禁止，不仿真 CommonMark 的 HTML 块状态机（档案库 r3 amendment 的继承，禁令同时写入注入文本）。

**校验失败的两类可确定性整改项**（Amendment 2；§6.5.4 校验类补发的触发判据，唯一规范）：**已知值缺陷** = 下列字段的缺失、类型错或取值与通道已知值不等——`verdict_schema`（常量）、`authorization_disclaimer`（常量）、`subject` / `stage` / `round`（与评审请求相等）、`candidate` 与 `candidates`（第 8 条，与清单相等）、`accepted_residuals_acknowledged`（第 7 条，与评审请求相等）；这些字段的正确值由通道确定，不含评审方判断。**叙述缺陷** = 第 5 条「每条 finding 在叙述正文有标题级小节」、第 13 条、raw HTML 行禁令，以及 §6.4 叙述约定的恢复失败（首两行形态、节缺失或重复、行形态）。其余失败——第 1 至 4、6、9、10、11、12、14 条，以及判断字段的缺失、类型错或 finding id 文法失败——不属可确定性整改项。**判断字段** = §6.5.1 全部字段减去已知值缺陷所列字段 = `verdict`、`human_decision_required`、`question_assessments`、`findings`、`previous_findings_disposition`、`scope_files_read`、`tools_used`。实撞：`repo:KB-01` 其五（机读块缺常量字段 `verdict_schema` 即 INVALID 且不补发，CL-34 第 8 项其二登记为后续输入）与 repo-od-09:KB-02 其一（机读块完好、叙述排版不合契约即整份作废）。

#### 6.5.3 严格发布文法、信封包容三级与叙述正文的确定性分离（gov-t8:OD-02 其八；R1-B6、R2-B1 整改）

**严格发布文法**（发布的判词文件恒满足；handoff 协议 `verdict` 锚与 gov-t11 读端只实现此文法）：文件第 1 行为围栏 opener ` ```review-channel-verdict `（零缩进、无尾随文本），随后为**评审方原样输出的 JSON 值区段字节**（不重编码、不改键序与空白），随后一行闭栏 ` ``` `，随后一个空行，随后是叙述正文；全文恰一个该围栏块；叙述正文不含 raw HTML。

**候选块的五段分区与叙述正文的确定性分离**（R3-B1 整改）：对评审方原始最终消息按行顺序扫描；处于任何候选块之外时，凡 opener 行（允许至多三空格缩进、三到五个反引号、信息串大小写不敏感匹配 `review-channel-verdict`）即开启一个候选块，其分区固定为：① opener 行；② **前缀** = opener 行末至第一个 `{` 之前的字节；③ **JSON 值区段** = 自该 `{` 起以 JSON 解码器 `raw_decode` 取得的恰一个 JSON 值的字节（逐字节保留；`raw_decode` 在值内部按 JSON 文法前进，值内字符串含换行或反引号不构成闭栏）；④ **后缀** = 值终点至闭栏行之前的字节；⑤ 闭栏行（值终点之后遇到的第一个同字符、行首、无尾随文本的围栏行；文件先结束即闭栏缺失）。前缀含非空白字节 → 该候选块判为不可解析（进入三级；前缀不是信封，也不是 JSON，不做包容）；后缀的非空白文本 = 收尾散文；`raw_decode` 失败 → 不可解析。候选块之外的全部行与各收尾散文按原顺序拼接即**叙述正文**。候选块数 = 0 或 ≥ 2、或唯一候选块不可解析即三级；恰一个可解析候选块进入一级或二级判定。

**直接接口 wrapper 的原始成员 span 提取**（§7.4 路径；R3-B1 整改）：对 wrapper 原始文本，自顶层 `{` 起用 `raw_decode` 逐成员扫描——解码键字符串取得键与其终点、跳过空白与 `:`、对值调用 `raw_decode` 取得值的起止偏移——直到取得 `machine` 成员；其起止偏移之间的字节即 JSON 值区段（逐字节保留，不经 `json.loads` 再序列化）；`narrative` 成员的值经 JSON 字符串解码后为叙述正文。顶层不是对象、`machine` 缺失或重复、任一成员 `raw_decode` 失败 → INVALID（本路径不补发，§7.4）。

包容只作用于信封，JSON 值区段一个字节都不改；每级结果写入 Receipt `extraction` 字段：

| 级 | 情形 | 处置 | `extraction.tier` |
|---|---|---|---|
| 1 | 恰一个候选块，位于消息开头，opener 与闭栏形态完全合规，JSON 值区段可解析且无收尾散文 | 发布 = 原 opener 形态规范化后的块（JSON 字节原样）+ 叙述正文 | `strict` |
| 2 | 恰一个候选块，且下列缺陷之一或多个：闭栏缺失（区段到文件末尾）、opener 缩进 / 反引号数 / 大小写偏差、JSON 后有收尾散文、块不在消息开头；JSON 值区段可解析 | 同上发布；每项规范化动作逐条记 repair：`missing-closing-fence` / `opener-indent` / `fence-length` / `info-string-case` / `trailing-content` / `block-relocated` | `repaired` |
| 3 | 候选块数 ≠ 1，或唯一候选块不可解析（前缀含非空白字节、或 `raw_decode` 失败） | 不做启发式改写；调用工具路径进入补发轮（§6.5.4）；直接接口路径不自动补发（§7.4）；补发失败或不适用即 INVALID | `reemitted` / `invalid` |

Receipt 记 `raw_final_message_sha256` 与 `raw_block_sha256`（原候选块字节）供审计比对；发布文件内 JSON 值区段的字节恒等于原候选块内的 JSON 值区段字节（自测第 20 类断言）。三级发布 = 补发得到的 JSON 值区段（原样字节）+ 原始消息的叙述正文（原始候选块全部剔除，不与补发块并存）。一级与二级的块在 §6.5.2 校验失败、且失败只落在可确定性整改项时，同样进入补发（校验类，§6.5.4）；`extraction.tier` 只描述发布 JSON 值区段的来源，补发触发类另由 `extraction.reemit_trigger` 承载（Amendment 2）。

#### 6.5.4 补发轮与不变性核对

**触发类闭集**（Amendment 2；台账 repo-od-09:KB-02 其一、CL-34 第 8 项其二）恰二：**信封类** = §6.5.3 三级情形（候选块数 ≠ 1，或唯一候选块不可解析）；**校验类** = 机读块可解析（一级或二级）而 §6.5.2 校验失败，且全部失败项都属**可确定性整改项**（已知值缺陷或叙述缺陷，§6.5.2 末段闭集）——存在任一其他失败项即不补发、判 INVALID：判断字段的缺陷不能由补发修复，要求评审方改判断即替评审方改判断。两类均只在本轮走调用工具适配器时适用（直接接口路径两类均不适用，§7.4）。通道在**同一 review attempt 内**自动发起**恰一次**补发调用（`review` 内默认自动执行，`--no-reemit` 关闭并记入 Receipt，关闭时两类均按原判 INVALID、失败码 `reemit-disabled`）；**补发恒至多一次**：补发结果再次落入任一触发类时不再补发，按下文失败规则判 INVALID。**补发不是 attempt**（gov-t8:OD-02 其十七；R17-B1 至 R20-B1 的问题类由此整体消失）：同一 attempt 目录、同一阶段状态记录、同一把同轮文件锁、同一份 Receipt；不新增子命令、mode 值、分类值、状态转换表行、Receipt 阶段或能力证据路径。补发调用与首次调用同一 Profile、同一适配器，不重读被审输入；输入 = 评审方自己的原始最终消息 + 按触发类渲染的补发指令——**信封类**指令 = 「原样重发机读块，不得改动任何判断，不得新增或删除 finding」（叙述不重发）；**校验类**指令 = 通道渲染的已知值字段正确取值清单（逐字段一行）+ 以原机读块实际值渲染的叙述骨架（§6.4 同源渲染：首两行、每条 finding 的标题行、逐题行、r2+ 逐条上一轮 finding 行均已填实）+ 「重发完整判词：机读块内判断字段逐字保持原值、已知值字段按所给值填写；叙述按骨架逐行输出、只在各 finding 标题之下填入原叙述的对应内容；不得改动任何判断」。其原始消息与运行证据以 `reemit-` 前缀落同一 attempt 目录（`reemit-reviewer_last_message.md`、`reemit-runtime_events.jsonl`、`reemit-stderr.log`），阶段状态记录在补发调用前后各重写一次（`calling` / `called`，§6.1，记录内以 `call_index = 2` 区分）；补发调用返回或抛出异常后做下文核对与补发调用失败的分类（Amendment 2 在此处的锁值引用件复核已随 Amendment 4 退役）。

**不变性核对**（R1-B6 整改；Amendment 2 按触发类分立，唯一规范）。**信封类**：通道按 §6.4 叙述约定从**原始叙述正文**机械恢复下列字段，与补发块逐项比对，任一不等即整体 INVALID、分类 `reviewer_output_invalid`：`verdict`；`human_decision_required`；finding 的 id 集合、每条的 severity 与 title；每题的 assessment；r2+ 每条上一轮 finding 的 disposition。不能从叙述恢复的字段（`location`、`origin`、`summary`、`evidence_refs`、`finding_ids` 引用、`accepted_residuals_acknowledged`、`scope_files_read`、`tools_used`、`candidate`、`candidates`）从补发块采纳，并在 Receipt `extraction.reemit_unverifiable_fields` 逐项列出，判词读端据此知道哪些字段只有补发一方的自述；发布 = 补发块 + 原始叙述正文（§6.5.3 三级发布）。**校验类**：原机读块在场，核对面因此更强——补发消息按 §6.5.3 分区取得补发块与补发叙述（补发消息自身的信封缺陷按二级规范化，三级即失败）；**判断字段**（§6.5.2 末段闭集）逐字段与原机读块经 canonical JSON 编码（§6.2 第 5 条）后逐字节相等，任一不等即 `mismatched_fields` 记该字段名、整体 INVALID；已知值字段按 §6.5.2 规则核对（不与原块比对——原块该处正是缺陷）；`reemit_unverifiable_fields` 为空数组（全部字段均有原块或通道已知值可核）；发布 = 补发块 + 补发叙述，随后经 §6.5.2 全部规则校验（含第 13 条对补发叙述的恢复比对）。Receipt `extraction` 记 `tier`（两类均为 `reemitted`：发布的 JSON 值区段来自补发调用）、`reemit_trigger`（闭集 `envelope` | `validation`，未补发为 null）、`reemit_reasons[]`（触发补发的原始失败项，`verdict_problems[]` 同一文法；未补发为空数组）、`reemit_raw_message_sha256`（补发原始消息字节的 SHA-256）、`reemit_unverifiable_fields[]` 与**不变性核对结果** `invariance_check {status, mismatched_fields[]}`（R22-B3 整改，其十七明定字段）：`status` 闭集 `passed`（全部核对字段相等）/ `mismatch`（`mismatched_fields` 列出每个不等字段名、非空）/ `not_reached`（补发调用失败或返回仍不可解析，`mismatched_fields = []`）；未发起补发时整对象为 null；`status = mismatch` 时 `verdict_problems[]` 逐字段另记 `reemit-invariance-mismatch:<field>`；原始正文以「未校验笔记」留 attempt 目录，不算证据（档案库契约 §17 规则 8 的继承）。补发不消耗轮次额度、不产生第二份 Receipt；**补发调用的分类优先规则**（R22-B1 整改，唯一规范）：attempt 分类取**最后一次调用**的结局——补发调用发生提供方不可达、认证失败、运行时拒绝配置、超时或传输失败时，按 §6.7 同名基础设施行分类（与首次调用同规则，失败码另记 `call_index = 2`，`invariance_check.status = not_reached`）；补发调用返回但仍不可解析 → `reviewer_output_invalid` + 失败码 `reemit-unparseable`；不变性核对不符 → `reviewer_output_invalid` + 失败码 `reemit-invariance-mismatch`；校验类补发后 §6.5.2 仍有失败项（已知值仍错、叙述仍不合约定，或新出现的其他失败）→ `reviewer_output_invalid` + 失败码 `verdict-invalid`（`extraction.reemit_trigger` 使该情形与未补发的 `verdict-invalid` 可区分）；秘密命中与发布失败按既有规则。§6.7 基础设施四行对两次调用一体适用，其「补发后仍 INVALID」只指调用成功但输出或核对失败。任一失败后下一 attempt 按 §6.7 规则 7 由 caller 归因后发起、仍是新 attempt。

**校验类的边界如实声明**（Amendment 2）：校验类补发把叙述的结构行由通道自机读块渲染并要求逐字采用，该路径下叙述不再是机读块的独立来源；Receipt `reemit_trigger = validation` 如实标记，读端据此知道叙述结构行为通道所定（§15 残留）。判断字段与原块的逐字节相等使补发无法改动任何判断——这是校验类不违反「本体坏则同一评审方补发、包容不替评审方改判断」（§15）的机械保证；通道给出的只有它本就已知的值与它本就要求的行形态。

### 6.6 Receipt 与 effective Profile

Receipt（`receipt_schema = "review-channel-receipt/v2"`）每次 attempt 必产，含 preflight 失败；恒最后写。字段按组：

- **身份**：attempt_id（UTC 时间戳 + 8 位随机 hex）、subject、stage、round、task_record、mode（preflight / probe / review）。
- **分类与结局**：`classification`（§6.7）、`call_path_proof` / `profile_binding` / `verdict_validation` 三维（§6.11）、`attempt_outcome`（闭集 `governed_verdict` | `receipt_only` | `preflight_failed`；`governed_verdict` ⇔ 判词发布成功；`probe_completed` 的成功终态取 `receipt_only`）、`verdict_published`（布尔；Receipt 的身份由位置承载，review 的成功 Receipt 只在 rename 成功后才作为 Receipt 存在，故该字段为 true 的 Receipt 必位于已发布轮内或是其同 inode 副本，§8.2「Receipt 的真实性与总量性」）、`capability_suggestion`（仅建议，Registry 由 Human 凭 Receipt 独立提交更新）。**被继承读端与 Registry `receipt_ref` 核验引用的 Receipt 字段闭集**（R2-B6、R5-B2 整改）= `receipt_schema`、`attempt_id`、`subject`、`stage`、`round`、`mode`（来源判别字段，闭集 `preflight` / `probe` / `review`）、`receipt_phase`、`classification`、`attempt_outcome`、`call_path_proof`、`profile_binding`、`verdict_validation`、`verdict_published`、`verdict_path`、`verdict_sha256`、`effective_profile`（含其 `profile_schema`）、`input_manifest_sha256`；这些字段的存在与值域是 Receipt schema 的冻结部分。
- **被审输入**：`input_manifest_sha256` 与清单相对路径。**不内嵌清单本体**（gov-t8:OD-02 其一、其四；`legacy:OD-17` 路径二）——清单已作为四件最低成员之一独立入仓，Receipt 内嵌即同一花名册每轮入库两遍。
- **判词**：`verdict_path`、`verdict_sha256`、`raw_final_message_sha256`、`raw_block_sha256`、`extraction {tier, repairs[], reemit_trigger, reemit_reasons[], reemit_raw_message_sha256, reemit_unverifiable_fields[], invariance_check {status, mismatched_fields[]}}`（R23-B2 整改：`invariance_check` 是 `extraction` 的冻结成员；未发起补发时该成员为 null，发起后必填，值域见 §6.5.4。Amendment 2 增 `reemit_trigger`（闭集 `envelope` | `validation`，未补发为 null）与 `reemit_reasons[]`（未补发为空数组），同为 `extraction` 的冻结成员；增员不换 Receipt schema 号——被继承读端与 Registry `receipt_ref` 核验引用的字段闭集不含 `extraction`，先例 = R23-B2 在 v2 内增 `invariance_check`；换号会使 freeze-record 设计 §5.3 按 `receipt_schema` 取字段的两值闭集失配，属该设计 amendment）、`verdict_problems[]`、`human_decision_required`、`delivery`（`tool` | `inline`）、`decisions_sha256`（r2+ 取上一轮决定文件字节的 SHA-256，r1 为 null；Amendment 4 增员不换号，与 Amendment 2 同据；`standard_questions_effective` 成员自 Amendment 4 起退役：被继承读端与 `receipt_ref` 核验引用的字段闭集不含它，去员与增员同据）。
- **effective Profile**（内嵌，`profile_schema = "review-channel-effective-profile/v3"`）：caller、作者 provenance（`human_only`、`authors` 三元组列表原样、派生的 `model_vendors` 集合）、route provider（id、kind、runtime）、requested / response model、logical_model_match、resolved_upstream、claimed vendor、routing_mode、transport、requested / effective effort 及来源、`provider_effective_behavior`、sanitized overrides 及来源、selection_source、**runtime_version（只记录，§6.11）**、registry_revision + registry_sha256、**contract_version + contract_design_sha256（只记录，不作继承门，§6.11）**、request_sha256、input_manifest_sha256、verdict_path + verdict_sha256、round 与 attempt 身份、process 事实、usage、事件计数与请求 id 计数（提取无果才 `unknown`）、retry 事实、model identity assurance（恒 operational-claim）、继承上下文（本轮问题 id 集合、投递名集合、任务书名）、`reviewer_tool_surface`、精确重物化所需的非秘密绑定（key / base 变量名或认证文件路径名 + auth_mode）。**字段按确定时点分三组**（R16-B2 整改；状态记录与补产 Receipt 按组填充，§6.1）：**选定组**（封存时确定）= caller、作者 provenance、route provider、requested model、resolved_upstream、claimed vendor、routing_mode、transport、requested effort 及来源、sanitized overrides 及来源、selection_source、registry_revision + registry_sha256、contract_version + contract_design_sha256、request_sha256、input_manifest_sha256、round 与 attempt 身份、model identity assurance、继承上下文、`reviewer_tool_surface`、非秘密绑定；**调用组**（调用返回后确定）= `calls[]`（R22-B2 整改：每次适配器调用恰一项、按 `call_index` 升序——首次调用 1、补发调用 2；一经记录从不覆盖），每项含 `call_index`、response model、logical_model_match、effective effort 及来源、`provider_effective_behavior`、runtime_version、process 事实、usage、事件计数与请求 id 计数、retry 事实、该次调用自身的 `call_path_proof` 与 `profile_binding`，**以及三个归约字段** `effective_effort`（及来源）、`response_model`、`logical_model_match`（R24-B2 整改：属调用组、每次 `called` 写入时由 `calls[]` 重算，规则见下「单值消费端的 attempt 级归约」）；**发布组**（⑥ 落位后确定）= verdict_path + verdict_sha256。三组并集恰为上列全部字段，`profile_schema` 恒在场；未到确定时点的组整组为 null，任何写端不得以占位值填充。**attempt 级三维由 `calls[]` 保守聚合**（R22-B2 整改，唯一规范；§6.11 三维表定义的是单次调用的判定）：`call_path_proof` = 全部调用皆 `PROVEN` 才 `PROVEN`，否则任一 `NOT_PROVEN` 即 `NOT_PROVEN`，否则 `INDETERMINATE`；`profile_binding` = 任一 `MISMATCH` 即 `MISMATCH`，否则任一 `INSUFFICIENT` 即 `INSUFFICIENT`，否则 `SUFFICIENT`；`verdict_validation` = 对最终发布块的校验结果（§6.5.2，含不变性核对）。补发因此只能维持或降低三维、不能抬升：首次调用绑定不足而补发充分的组合聚合为 `INSUFFICIENT`，不形成 `REVIEW_ENABLED` 建议。**单值消费端的 attempt 级归约**（R23-B1、R24-B1 整改，唯一规范）：调用组内三个归约字段 `effective_effort`（及来源）、`response_model`、`logical_model_match`——全部 `calls[]` 项的对应值逐项相等时取该值，任一不等时三字段整体取 null 且 attempt 级 `profile_binding` 恒为 `MISMATCH`（补发要求同一 Profile、同一适配器，不等即绑定冲突证据）；`runtime_version` **不参与归约**（其十四：版本只作事实，任何取值都不触发拒绝、降级或重绑定），attempt 级只在运行时组按 §7.6 记录，各次调用的版本留在 `calls[]` 单项；§6.9 继承、§6.11 `receipt_ref` 核验与 §6.7 三维「实际值」一律只消费 attempt 级字段（三维即聚合值），从不读取 `calls[]` 单项；null 在核验端即拒绝、在继承端即 `inherit-unanchored`。
- **轮次额度**：`round_budget {max_rounds, source: default | request, extensions: [...], allowed_rounds, round_index, exhausted: bool}`（§6.10）。
- **授权**：`formal_review_authorized_by_owner`、`invocation_authorization` 的 SHA-256 摘要（早期 Receipt 不逐字持久化自由文本，档案库 R5-B4 的继承）。
- **运行时**：`runtime {adapter, tool_version | api_endpoint_id, changed_within_attempt, changed_across_rounds}`（R25-B1 整改，确定性表示：`tool_version` / `api_endpoint_id` 恒取**首次调用**（`calls[]` 首项）的值，补发调用的版本只留在 `calls[]` 第二项；`changed_within_attempt` = 两次调用的版本字面不等（单次调用恒 false）；`changed_across_rounds` 按四种情形取值（R26-B1 整改，总函数）：无上一轮 Receipt（首轮或上一轮 review-skip）→ null；上一轮 `adapter` 与本轮不等（显式跨适配器改选，互斥成员不可比）→ `true`；`adapter` 相等且 `tool_version` / `api_endpoint_id` 字面不等 → `true`；`adapter` 相等且字面相等 → `false`——不区分继承与显式同适配器改选，比较对象恒为上一轮 Receipt 的 `runtime` 组与本 attempt 首次调用值；三者都是可见事实，不参与任何判定）——版本只作事实，任何取值都不触发提醒、降级或重绑定（gov-t8:OD-02 其十四；§6.11）。
- **诊断层摘要**：各诊断 artifact 的 SHA-256、秘密泄漏标记、环境状态报告、UTC 时间戳。

**按阶段的条件 schema**（R3-B5 整改）。Receipt 带 `receipt_phase`，闭集与各组字段的必填 / 置 null 规则：

| `receipt_phase` | 到达条件 | 必填 | 恒为 null |
|---|---|---|---|
| `routed` | 最小可路由解析通过，Request 完整校验未通过或封存前失败 | 身份组（四路由字段）、分类与结局（三维取定值 `NOT_PROVEN` / `INSUFFICIENT` / `NOT_REACHED`，`attempt_outcome = preflight_failed`，`verdict_published = false`）、失败码、授权摘要、诊断层摘要 | `effective_profile`、`input_manifest_sha256`、判词组、轮次额度组、运行时组 |
| （补产 `interrupted`） | attempt 进程在写出 Receipt 前终止，由后续 preflight 补产（§8.2 第 6 步）；`receipt_phase` 取 `attempt.json.phase`（五态之一） | **自带闭集（R15-B2 整改，不引用正常行的必填集合）**：恒有——`receipt_schema`、`attempt_id`、`subject`、`stage`、`round`、`task_record`（缺席 null）、`mode`、`receipt_phase`、`classification = interrupted`、`failure_code = interrupted`、`attempt_outcome = preflight_failed`、`verdict_published = false`、`request_sha256`、`invocation_authorization_sha256`、`formal_review_authorized_by_owner`、三维、`synthesized_by`（恢复者身份 = 其 pid + `pid_start` + 所属 attempt_id 或 preflight 标识）、`utc`（恢复时刻）；`sealed` 及之后另有——`effective_profile`（按记录内三组填充状态原样复制：`sealed` 与首次 `calling`（`call_index = 1`）记录只含选定组，补发的 `calling`（`call_index = 2`）记录含选定组 + `calls[]` 恰首项，`called` / `validated` 记录含选定组 + 调用组（`calls[]` 与三个归约字段，按记录内值原样），发布组恒 null；补产不计算、不更新其任何字段）、`input_manifest_sha256`、`round_budget`、`decisions_sha256`、`delivery`；`called` 及之后与补发的 `calling`（`call_index = 2`）另有——运行时组与 `effective_profile.calls[]`（按记录内已完成的调用项原样；补发调用崩溃于其 `calling` 态时 `calls[]` 只有首项）；`validated` 另有——`extraction`。三维取值：`routed` / `sealed` = `NOT_PROVEN` / `INSUFFICIENT` / `NOT_REACHED`；`calling`（`call_index = 1`）= `INDETERMINATE`（调用可能已到达提供方）/ `INSUFFICIENT` / `NOT_REACHED`；`calling`（`call_index = 2`）= 首项与 `INDETERMINATE` / `INSUFFICIENT` 的保守聚合 / `NOT_REACHED`；`called` = 记录内 `calls[]` 的保守聚合值 × 2 / `NOT_REACHED`；`validated` = 记录内实际值 × 3（含 `INVALID`）。`synthesized_by` 与 `utc` 是恢复事实，不由记录派生；两个并发恢复者只保证恰一份 Receipt（link 排他），不保证字节相同 | 上列之外全部字段恒 null（含判词组、诊断层摘要；`extraction` 在 `validated` 之前为 null） |
| `sealed` | Request 校验通过、Profile 选定、被审输入封存后调用前失败 | 上一行 + `effective_profile`（选定组必填；调用组与发布组 null）、`input_manifest_sha256`、轮次额度组 | 判词组（`verdict_path` 等）、运行时组的版本字段 |
| `called` | 调用已发生（无论结局） | 上一行 + `effective_profile` 调用组（`calls[]`，一次调用一项）、运行时组、三维取 `calls[]` 的保守聚合值 | 判词组中未发生的项（未发布时 `verdict_path` / `verdict_sha256` 为 null，`extraction` 仍必填） |
| （状态记录专用 `calling` / `validated`） | `calling` = 已发起外部调用、尚未返回；`validated` = 判词校验已完成、尚未发布。二者只出现在 `attempt.json.phase` 与补产 Receipt 的 `receipt_phase`，正常写出的 Receipt 不取这两值 | 见补产行 | 见补产行 |
| `completed` | attempt 达到终态成功：review 为判词校验 VALID 且四件经 ⑥ 一次 rename 落位（成功 Receipt 只在落位后才作为 Receipt 存在，`verdict_published = true`、`attempt_outcome = governed_verdict`）；probe 为 `probe_completed` | 全部适用字段（probe 的判词组恒为 null，`verdict_published = false`） | 无 |

**耐久性不是 Receipt 字段，是消费端按落点判定的事实**（R4-B2、R5-B2 整改；Receipt 一经写入不改字节，exact copy 因此恒成立）。一份 Receipt 可作 capability 证据，当且仅当：其引用路径位于**耐久落点**——review 的 `tracked_round_dir/receipt-r<N>.json`，或 capability 证据落点 `records/diagnostics/review-channel/<YYYY-MM-DD>/receipt-<attempt_id>.json`（布局权威 §6.6 既有目录类「日期化诊断快照，按需建立」；先例 = handoff-protocol Owner Decisions D2 演练证据落点）——且该文件**受 Git 跟踪**（`git ls-files` 命中，消费端机械核对）。probe 成功 Receipt 与「判词 INVALID 但 `PROVEN + SUFFICIENT`」的 review Receipt 都留在 attempt 目录，由 Human 随 Registry 能力更新 exact copy 到 diagnostics 落点并提交，并在 Registry capability 条目内同时记录 `receipt_commit`（引入该文件的提交的完整 SHA）与 `receipt_sha256`（R6-B2、R7-B2 整改）；这两条都是状态转换表第二行「建议 `PROBED`」的可达证据路径。**diagnostics 落点 Receipt 的身份锚是 Git 提交 blob，不是活体 Registry 的自证**：装载时以 `git cat-file -p <receipt_commit>:<receipt_ref>` 取得该提交中该路径的 blob，要求 blob 的 SHA-256 = `receipt_sha256` = 工作树文件字节的 SHA-256（三方相等），且 `receipt_commit` 是当前 `HEAD` 的祖先（`git merge-base --is-ancestor`）；任一不成立即拒绝装载。工作树内同时改写 diagnostics 文件与 Registry 哈希因此无法通过——blob 属已提交历史、`main` 受保护 MR-only。信任边界如实声明：`receipt_commit` 所指提交本身由 Human 提交，伪造整套 Receipt 并提交属人为越权，留完整 Git 痕迹，超出机械门职责（档案库 runner 设计 §19 同款残留的继承，§15）。tracked 轮目录内的 Receipt 自 Amendment 4 起无登记本字节锚（`locks` 门与证据登记本已随减重第 2 步退役，§8.4），装载时按同一三方相等规则（Git 提交 blob）核对（`receipt_commit` 同样必填）。原件在场时另作逐字节比对（在场即多一重核，不在场不放宽）。Registry `receipt_ref` 核验按声称状态核对（本条为 `PROBED` / `REVIEW_ENABLED` 装载条件的唯一规范表述，§6.11 引用之）：**先按 `mode` 判来源**：`mode = preflight` 不是 attempt、无 Receipt；`mode` 缺失或不在闭集即拒绝。`PROBED` 恰两条路径——`mode = probe` 且 `classification = probe_completed`、三维 `PROVEN + SUFFICIENT + NOT_REACHED`；或 `mode = review` 且 `classification = reviewer_output_invalid`、`receipt_phase = called`、三维 `PROVEN + SUFFICIENT + INVALID`——两者都须位于 diagnostics 耐久落点；`REVIEW_ENABLED` 须 `mode = review`、`receipt_phase = completed`、`completed_with_valid_verdict`、三维 `PROVEN + SUFFICIENT + VALID` 且 `verdict_published = true`、位于 `tracked_round_dir`；继承读端使用同一原轮路径，并按 §8.5 接受当前受跟踪原件或可验证历史原件，仍要求 `verdict_published = true` 及全部继承校验。`routed` / `sealed` 阶段的 Receipt 只作审计与失败归因。每个阶段各有失败夹具证明 Receipt 可构造（§12 第 19 类）。

### 6.7 attempt 分类闭集

按「模式 × 结果」穷举（R2-B9 整改；档案库台账 OD-04 / KB-01 一类「分类闭集缺值」问题的处置）。每个 attempt 恰一个分类；分类先于退出码，退出码由分类唯一映射（§5.3）——`interrupted` 例外：它由他进程补产，不对应本进程退出码（§5.3 末行）：

| 结果 | preflight（非 attempt） | probe | review |
|---|---|---|---|
| 四路由字段缺失或不合文法、JSON 不可解析 | `request-unrouteable`（stderr 报告，无 Receipt） | 同左（无 attempt、无 Receipt） | 同左 |
| 路由通过后任一 preflight 检查拒绝 | 报告失败码 | `preflight_failed`（Receipt 记失败码） | `preflight_failed` |
| 运行时报告提供方不可达 | 不适用 | `provider_unavailable` | `provider_unavailable` |
| 认证失败（含登录态缺失） | 不适用 | `authentication_failed` | `authentication_failed` |
| Host 取消执行（H-01，仅产品端口） | 不适用 | `cancelled_by_host` | `cancelled_by_host`；无受治理判词，不记 Reviewer FAIL，不消耗输出补发预算 |
| ExecutionPort 失败（H-02，仅产品端口） | 报告端口静态拒绝码，不产 attempt | `execution_port_failure` | `execution_port_failure`；保存静态 failure code 和实际执行引用，不折叠为输出无效 |
| 运行时拒绝配置 | 不适用 | `runtime_rejected_config` | `runtime_rejected_config` |
| 超时或传输失败 | 不适用 | `timeout_or_transport_failure` | `timeout_or_transport_failure` |
| 进程 / 请求成功但输出无效（probe：载荷不匹配或空；review：三级包容与补发后仍 INVALID（`reemit-unparseable`）、不变性不符（`reemit-invariance-mismatch`）、校验类补发后仍不合契约或判断字段缺陷不补发（`verdict-invalid`，Amendment 2；含 §6.5.2 第 14 条，Amendment 4）、秘密命中、发布失败；补发调用的基础设施失败按本表对应基础设施行分类、不入本行（§6.5.4 分类优先规则）） | 不适用 | `reviewer_output_invalid` | `reviewer_output_invalid` |
| 成功 | 不适用 | `probe_completed`（`PROVEN`，载荷精确匹配；Receipt 经 Human exact copy 到 diagnostics 落点并提交后可作 capability 证据，§6.6） | `completed_with_valid_verdict`（review；含经补发后交叉核对通过的情形，§6.5.4） |
| 通道内部异常（按模式与阶段） | 退出码 2 | 调用前 `preflight_failed` + `internal-error`（三维定值）；调用后 `reviewer_output_invalid` + `internal-error`（三维 = `INDETERMINATE` / 适配器实际值 / `NOT_REACHED`）；Receipt 写入自身失败 → 退出码 2，本进程无 Receipt，由后续 preflight 补产 `interrupted` | 调用前同左；调用后（含补发调用后）`reviewer_output_invalid` + `internal-error`（三维 = attempt 级聚合值 × 2 / `INVALID`，§6.6）；Receipt 写入自身失败 → 退出码 2，由后续 preflight 补产 `interrupted` |
| attempt 进程在写出 Receipt 前终止（崩溃、被杀、Receipt 写入失败） | 不适用 | `interrupted`（由后续 preflight 前置补产，R12-B1 整改：`receipt_phase` 取 `attempt.json` 所记 phase（五态之一），字段闭集与三维按 §6.6 补产行逐态取值（R16-B2 整改：该行是补产 Receipt 的唯一规范，本表不另列取值），`attempt_outcome = preflight_failed`，失败码 `interrupted`；tracked 目录已有该 attempt 的 Receipt 时不补产而是回链） | 同左 |

**启动期失败（无 attempt、无 Receipt）恰一种**（R3-B6 整改；Amendment 4 起）：`request-unrouteable`（退出码 1），只有 stderr 报告（`runtime-identity-not-allowed` 随运行时身份资格检查于 Amendment 4 退役）。**内部异常按模式与发生阶段分类**（R3-B6、R4-B3 整改，§5.3 / §6.7 / §6.11 引用同一闭集）：调用前（`routed` / `sealed`，任一模式）→ `preflight_failed` + 失败码 `internal-error`，三维取定值 `NOT_PROVEN` / `INSUFFICIENT` / `NOT_REACHED`；review 调用后（含补发调用后）校验或发布中 → `reviewer_output_invalid`，`call_path_proof` 与 `profile_binding` 取调用的实际判定值、`verdict_validation = INVALID`，失败码 `internal-error`；probe 调用后（载荷比对或 Receipt 组装中）→ `reviewer_output_invalid`，`call_path_proof = INDETERMINATE`（载荷未能确认）、`profile_binding` 取适配器实际判定值、`verdict_validation = NOT_REACHED`（probe 恒不达校验），capability 建议按状态转换表第三行（不高于 `UNVERIFIED`），不得形成能力证据；异常发生在 Receipt 写入本身 → 以 stderr 报告并退出码 2（该 attempt 目录内暂无 Receipt，由后续 preflight 前置补产 `interrupted` Receipt，§8.2 第 6 步；**每个已分配的 attempt 最终恰有一份可观察 Receipt**）。秘密泄漏命中的 attempt 恒维持保守分类（不使用 `probe_completed` / `completed_with_valid_verdict`），泄漏事实由 Receipt 专用字段承载。规则 7（无效后重试前先归因）与规则 8（无效 attempt 内容不算证据）原样继承（档案库契约 §17）；调用工具路径的信封类缺陷由通道归因为「信封」并自动补发，可确定性整改的校验类缺陷（已知值缺陷、叙述缺陷）同样由通道归因并自动补发（§6.5.4 两类触发，Amendment 2），两者都是对规则 7 的机制化补充。

Host 取消与 ExecutionPort 异常优先于 Reviewer 输出分类：取消无有效判词，端口故障不进入输出补发。`execution_port_failure` 只描述故障类别，不替代 §6.11 的调用链证据判定。产品端口按以下观察区分；Host 接收请求、排队或放行均不等于评审运行时成功应答：

| 端口观察 | 单次调用证据与动作 |
| --- | --- |
| 已明确拒绝且未放行 | `NOT_PROVEN`，无调用资格证据；保存端口静态拒绝码 |
| 已放行或放行结果未知，但尚无成功进程/请求和最终消息证据 | `NOT_PROVEN` 表示尚未证明，不能推断物理执行未发生；保存同一 execution.requestId，query 和预约保护，禁止重复 execute、释放资源或自动补发 |
| 已取得实际进程/请求完成证据 | 沿用 §6.11 与 §7 适配器观察点：成功应答且最终消息非空才 `PROVEN`；进程失败、超时或 HTTP 非成功为 `NOT_PROVEN`；成功但空消息为 `INDETERMINATE`；probe 另须精确 PROBE-OK |

`profile_binding` 取实际核对结果；取消/端口故障的 `verdict_validation=NOT_REACHED`，不发布判词、不提升 `PROBED` / `REVIEW_ENABLED` 或 ExecutionPort 的 `CALL_ONLY` / `REVIEW_ENABLED` 资格。若故障前已固定满足既有标准的实际成功调用证据，Receipt 保留该单次证明，但故障 attempt 本身仍不能用于能力提升。attempt 聚合继续按 §6.6 `calls[]` 保守规则，后续查询或补产不得覆盖已记录调用。§6.11 四行表对这两类只给三维组合，能力建议另受本段的失败分类限制。其他维护 CLI 内部异常仍按原模式/阶段分类；本段扩展仅用于产品 ExecutionPort，不把 Host 放行状态映射成维护适配器的成功应答。新增分类及产品端口适用性要同时更新 Receipt、Registry、继承读端与 fixtures；旧 Receipt 原字节和已有资格不追补、不自动升级，具体物理 schema 换号由 feature-t17 的受审实现设计明确后再施工，不把本文文字视作当前代码已支持。

畸形 `previous_round.evidence` 在完整 Request 校验阶段拒绝：ArchiveRef 形状与 kind 先于归档追随核对。可路由请求仍写失败 Receipt，归档失败请求时不遍历已判无效引用，原请求字节作为失败原件保存；不得把畸形引用当成有效前轮来源或降级放行。Definition Review 在 provider 调用前运行当前 task 模板结构核对，缺少/重复/乱序核心标题与身份不符直接 `preflight_failed`，九个核心 H2 和非权威通俗说明按模板解析，不让 Reviewer 代替结构门。

### 6.8 跨模型提供方资格

判定式与档案库契约 §9 逐条相同（gov-t8:OD-02 其六、其十一），比较改为大小写敏感精确比较（其十六，取值恒属 §6.11 `vendors` 闭集）：`reviewer_model_vendor ∉ artifact_author_model_vendors`；Caller 与调用工具不参与比较；聚合商是路由提供方不是模型提供方；集合为空、含 `unknown` 或含空串即拒（`human_only = true` 且集合为空除外）；无「主要作者」比例规则、无 same-vendor 例外。`delivery-method` 设计 §8 对「跨模型提供方按模型提供方不按工具」的裁定与此同源。

集合由评审请求 `artifact_author.authors` 的 vendor 派生（§6.1）：Claude Code 会话写稿时为 `["Anthropic"]`，Codex 会话写稿时为 `["OpenAI"]`，混合写稿时两者并列；`human_only = true` 时集合为空、任一已登记评审方均合格。维护模式评审请求由发起会话如实声明工具、模型与提供方三元组；产品模式由 hp 以实际读回模型和登记映射生成并核对，路由厂商不替代模型厂商，Host 不维护第二份厂商映射；Receipt 保留实际来源及映射身份（delivery-method §8 的机械可核义务）。

### 6.9 Profile 选择、继承与评审关闭

选择优先级（档案库契约 §8 与 runner 设计 §5 的继承，删去 standing selection 文件一级，见 §13 F）：

```text
1. 本轮评审请求显式 profile（provider + model 成对）
2. r2+：上一轮有效判词的 effective Profile 快照（经 previous_round 指向的 Receipt）
3. r1：Registry system_default
```

- 本级失败不下探；默认值不是 fallback（继承）。
- **每轮可显式指定与上一轮不同的 Profile**（gov-t8:OD-02 其五）：显式指定即优先级 1，Receipt 记 `selection_source = explicit-request` 与上一轮 Profile 的差异。
- 继承承载完整 Profile 快照（provider、model、claimed vendor、runtime、transport、attempt 级归约 `effective_effort`（§6.6；null 即 `inherit-unanchored`）、全部 sanitized overrides；当轮显式 overrides 优先，沉默则整套继承），并经**治理链锚定**（档案库 runner 设计 §5 的继承，本设计全文承载）：读端要求 `previous_round.receipt_path` 位于原 `tracked_round_dir`，且为当前受 Git 跟踪原件或 §8.5 验证的历史原件、所指 Receipt 记录成功（`classification = completed_with_valid_verdict`、`verdict_published = true`、`attempt_outcome = governed_verdict`）、其内嵌 effective Profile 经 `profile_schema` 版本与全字段校验、`verdict_sha256` 等于重算的上一轮判词哈希、subject 与 stage 与本轮一致、上一轮序号小于本轮；任一不成立即 `inherit-unanchored` 拒绝。**Registry 漂移防线**：快照携带精确重物化所需的非秘密绑定——claimed vendor、kind、runtime、transport、key / base 变量名或 `auth_source_path` + `auth_mode`；preflight 在秘密解析与任何调用之前把当前 Registry 条目与这些值逐一比对，任何不符（kind 换道、runtime 或 transport 改变、变量名轮换、认证路径漂移）即 `inherit-unmaterializable` 拒绝，不回退、不重解释。**继承不比对契约设计的哈希**（§6.11）。
- **评审关闭**：每轮可显式关闭评审，形态 = `review-skip` ruling（`ruling.template.md` 的 Type 闭集成员；原 task-artifact-schema §7.2），通道不介入；被关闭的轮不占轮次额度、不产生 Receipt。后一轮若再开启评审，`previous_round` 指向最近一轮**有效判词**，通道据 ruling 目录的存在核对中间轮已被 review-skip 裁定覆盖（缺裁定即 preflight 失败 `round-gap-unexplained`）。

### 6.10 轮次额度与加轮授权（gov-t8:OD-02 其四）

- 额度单点配置：Registry `defaults.max_rounds`（初值 2，Amendment 4；Owner 2026-09-06 裁定 B「封顶两轮」、裁定 F8 甲；r1 至 r4 为 7）；评审请求 `max_rounds` 可覆盖；代码不含字面量。
- 计数对象 = **已投递的业务轮数**：`tracked_parent` 下按原轴及 stage 规则得到的现存与 §8.5 历史轮目录并集中存在 `receipt-r<K>.json` 的轮的个数（§8.1 派生；每轮至多一份 tracked Receipt，§8.2）。review-skip 的轮没有 Receipt 故不计；补发是 attempt 内部调用、不是 attempt 故不计；preflight 失败与判词校验 INVALID 的 attempt（含 §6.5.2 第 14 条的原样重投）不产生 tracked Receipt 故不计。允许轮数 = 生效 `max_rounds` + 全部加轮记录的 `added_rounds` 之和。
- 轮序号约束与计数分离：本轮 `round` 的序号必须大于现存与历史原轮路径按既有命名空间得到的最大轮序号（严格递增；task 轴按 task/impl 分开，subject 轴原路径无 stage 前缀，不因本次调整另建序列），序号间隙只在每个缺失序号都被 review-skip ruling 覆盖时合法（§6.9 `round-gap-unexplained`）；序号不参与额度计算。
- 已投递轮数 ≥ 允许轮数时，本轮 preflight 拒绝，失败码 `round_budget_exhausted`，退出码 1，stderr 打出人读提示：已投递轮数、允许轮数、末轮阻断项数（取上一轮机读块）、加轮方式（在评审请求 `round_extensions` 追加一条 Human 授权记录）。
- 加轮 = Human 显式授权记录 `{authorized_by, at, added_rounds, note}`，随 Receipt 原样记入；可无限次追加；每次到额再问一次；通道永不因额度关闭。
- **到额三出口**（Amendment 4；Owner 裁定 B「两轮不收敛即停并交 Owner」的形态）：到额停报后 Owner 恒在三条出口内择一：其一，「加 N 轮」= 上条加轮授权记录，经通道续投；其二，带保留 re-Freeze 或带保留判 done（交付方法 §7.2：Human 终裁不被任何插件结论绑定，保留内容显式记入记录、判词不涂改），不经通道；其三，退回（候选不冻结、任务不判 done），不经通道。通道只承载其一，不为后两者新增任何字段或产物。
- 末轮判词为 PASS 时业务上不再发起下一轮，故「到额且末轮仍 FAIL」是该失败码的实际触发情形；若 caller 在 PASS 后仍发起（如确认轮），额度规则同样适用，不设例外。
- Receipt `round_budget` 字段（§6.6）是 `FR-28` Policy Gate（feature-t6）将来消费的事实面；本设计不做任何超出 preflight 拒绝之外的自动评估。

**耐久来源分流（CL-55）**：本节之前关于 current tracked 文件、Git blob 三方相等和 diagnostics 晋升的规则为 legacy-git 原接口。archive-v1 的 Receipt 完成真实性、双副本和最小结果锚按 §8.6.3/§8.6.5/§8.6.6；mode、三维、Profile 绑定与状态准入矩阵保持。旧固定 Git Receipt 的当前文件可缺席，解析规则由 §8.6.6 明确承接，不能因历史证据离开 HEAD 降低或抬升原能力事实。

### 6.11 capability 与 Registry

Registry（`registry_schema = "review-channel-registry/v3"`）是活体数据文件，不入冻结锁面（gov-t8:OD-02 其三；档案库 Amendment r4 的继承）；schema 形状变更须换号并走本设计 amendment，状态值演进由 Human 凭 Receipt 独立提交更新，通道不自写（通道只在 Receipt 给出 `capability_suggestion`）。

```text
registry_revision      正整数（排除 JSON 布尔），人工递增
defaults               {max_rounds: 2, timeout_seconds: 3600, effort: "high"}
system_default         {provider, model}（r1 无显式选择时的 Profile；改值 = 改本文件，走 Owner 提交纪律，不设代码常量核对——其十五）
providers.<id>:
  display_name
  kind                 official-direct | aggregator | builtin-native
  runtime              适配器标识，取值 = 单元内存在的 adapters/<runtime>.py（§5.2 数据驱动发现）
  transport            该 provider 的线协议，闭集 responses | chat | messages | builtin；须属该适配器声明的支持集
  key_env / base_env   official-direct / aggregator 必填（变量名，不存值）；builtin-native 禁填
  auth_source          builtin-native 必填：登录态认证文件路径名（非秘密）；其余 kind 禁填
  structured_output    runtime 为 http 类时可选：json_schema | json_object | none（§7.4）
  models.<slug>:
    claimed_vendor     须逐字命中本节 `vendors` 闭集（装载校验，表外拒绝）
    default_effort / supported_efforts
    max_input_bytes    runtime 为 http 类时必填（内联投递容量守卫）
    registered_equivalents   aggregator 用：应答模型标识的预登记等价映射
    capability:
      status           REGISTERED | CONFIGURED | UNVERIFIED | PROBED | REVIEW_ENABLED
      bound_transport  PROBED / REVIEW_ENABLED 必填：证据取得时的 transport（线协议，非 runtime）
      bound_effort     PROBED / REVIEW_ENABLED 必填：证据取得时的精确 effort，须属 supported_efforts
      receipt_ref      PROBED / REVIEW_ENABLED 必填；装载时机械核验（见下）
      receipt_commit / receipt_sha256   PROBED / REVIEW_ENABLED 必填：引入 Receipt 文件的提交 SHA 与其字节身份，装载时以提交 blob 三方核对（§6.6）
      evidence_runtime_version   可选，证据取得时的工具版本或接口标识，只记录、不参与任何判定
```

**模型提供方标识闭集**（gov-t8:OD-02 其十六；与 gov-t5 Freeze Record 设计对齐）。模型提供方（vendor）的合法取值是本设计正本内的封闭集合，冻结后随正本由冻结记录行承载身份（`locks` 门已退役）；Registry `claimed_vendor` 与评审请求 `authors[].vendor` 装载 / 校验时必须逐字命中（大小写敏感精确比较），表外 fail closed（失败码 `vendor-not-registered`）。新增厂商 = 本设计 amendment（与 gov-t5 的 amendment 节奏同批）。

| vendor（逐字） | 厂商 | 现役来源 |
|---|---|---|
| `Anthropic` | Anthropic | 继承档案库 Registry revision 7 |
| `OpenAI` | OpenAI | 继承档案库 Registry revision 7 |
| `DeepSeek` | DeepSeek | 继承档案库 Registry revision 7 |
| `Zhipu` | 智谱（GLM 系列） | 本设计新增（其十三直接接口路径的官方提供方） |

过渡期承诺：`Anthropic`、`DeepSeek`、`OpenAI` 三值逐字为本表冻结值的子集，gov-t5 现候选逐字抄录的三行在本设计冻结后改指本表。

**runtime 与 transport 是两个维度**：runtime 指哪个适配器驱动评审方（如 `codex-cli`、`http`），transport 指该适配器与提供方之间的线协议（如 codex 的 `responses` 或 `builtin`，http 的 `chat` / `responses` / `messages`）。一个 provider 条目绑定一个 runtime 与一个 transport；同一模型经不同 runtime 或 transport 接入即不同 Profile。

**能力绑定元组 = (provider, model, transport, effort)**，不含工具版本（gov-t8:OD-02 其三、其十四）；provider 已隐含 runtime，故元组不另列 runtime。effort 属元组是档案库 runner 设计 §4.2 `bound_effort`（R8-B1）的继承：证据只确立一个精确 effort，「模型支持某 effort」不等于「该 effort 已被证据确立」。

**capability 状态语义**（档案库契约 §6.2 的继承，本设计全文承载）：

- `REGISTERED`：Registry 认识该 Profile；无环境或认证事实。
- `CONFIGURED`：official-direct / aggregator 的 key / base 变量名可安全解析，或 builtin-native 认证文件 `present`；仅此不能越过本级。
- `UNVERIFIED`：曾达 `PROBED` / `REVIEW_ENABLED` 但 model、transport 或 effort 越出证据边界后的回退态；提供方文档、兼容声明或模型列表最多支持 Registry 注释，不能越过本级。
- `PROBED`：有可机械核验的 Receipt 证明该精确元组的 call-path（`PROVEN + SUFFICIENT + NOT_REACHED`，或 `PROVEN + SUFFICIENT + INVALID`）。
- `REVIEW_ENABLED`：有 Receipt 证明该精确元组产出过受治理判词（`PROVEN + SUFFICIENT + VALID`，`completed_with_valid_verdict`、`verdict_published = true`）。

**准入矩阵**（R1-B3 整改；档案库契约 §6.2「capability gate 区分允许尝试调用与允许接纳受治理判词」的全文承载）：

| 当前状态 | probe | review | 依据 |
|---|---|---|---|
| `REGISTERED` | 拒绝（`capability-not-configured`） | 拒绝 | 无环境或认证事实，零提供方调用 |
| `CONFIGURED` / `UNVERIFIED` / `PROBED` | 须 `formal_review_authorized_by_owner = true`（字面）；缺即拒绝（`formal-authorization-required`） | 同左 | `FR-41` 降级窗口内启动须 Owner formal 授权，授权标志随 Receipt 记录 |
| `REVIEW_ENABLED` | 直接准入 | 直接准入 | 证据在案 |

Registry 装载校验只在状态**声称** `PROBED` / `REVIEW_ENABLED` 而缺 `bound_transport`、`bound_effort` 或 `receipt_ref`，或 `receipt_ref` 核验不过时拒绝整个 Registry（缺证据只能降级、不得放行）；`CONFIGURED` / `UNVERIFIED` 条目无绑定是合法初始态，不触发拒绝。本仓通道各 Profile 自 `CONFIGURED` 起（§11 第 3 条），首次受治理评审经上表 formal 分支进入，成功即在同一次 attempt 建立能力 Receipt 并由 Human 凭该 Receipt 独立提交把状态升为 `REVIEW_ENABLED`。

preflight 对已绑定 Profile 的比对三支：本次选择的 (model, transport, effort) 与绑定不符 → 按 `UNVERIFIED` 走 formal 分支；相符 → 直接准入；工具版本与 `evidence_runtime_version` 不同 → **不比对、不报告、不提醒、不降级**，只在 Receipt `runtime` 组记录本次版本（其十四；较档案库 Amendment r5 去掉了 preflight 差异报告）。

`receipt_ref` 装载时机械核验（档案库 runner 设计 §4.2 第一档的继承；第二档 legacy allowlist 不继承，§11 第 3 条）：引用字节可解析为本设计的 Receipt（`receipt_schema` 吻合）→ 逐项比对内嵌 Profile 的 provider、model、transport、attempt 级归约 `effective_effort`（须等于 `bound_effort`；null 即拒绝，§6.6）、路由面（official-direct / aggregator 比 key / base 变量名，builtin-native 比 `auth_mode` / `auth_source_path`；未使用的那半须为 null）与结局（取值按 §6.6「Registry `receipt_ref` 核验按声称状态核对」一段的唯一规范表述）、**引用路径位于耐久落点、`receipt_commit` 为 HEAD 祖先、该提交中该路径的 blob 与工作树文件与 `receipt_sha256` 三方相等**（§6.6）；任一不符即拒绝装载。不解析散文。

**三维结果字段**（档案库契约 §6.2 的继承，本设计全文承载）：

```text
call_path_proof     PROVEN | NOT_PROVEN | INDETERMINATE
                    PROVEN = 评审方运行时经锁定的 runtime 与 transport 取得成功应答并捕获非空最终消息；
                    进程失败、超时或 HTTP 非成功状态 = NOT_PROVEN；进程或请求成功但最终消息为空 = INDETERMINATE；
                    probe 模式另要求最终消息恰为探针载荷 "PROBE-OK"（单行），否则 INDETERMINATE
profile_binding     SUFFICIENT | MISMATCH | INSUFFICIENT
                    SUFFICIENT = 结果可在 operational-claim 保证下绑定到锁定的精确 Profile：official-direct 与
                    builtin-native 的 model 身份锁在生成配置或请求体且无冲突证据；aggregator 须应答模型标识
                    命中 requested slug 或 registered_equivalents（logical_model_match = exact | registered_equivalent）；
                    应答模型标识与 Profile 冲突 = MISMATCH；应答侧模型不可见（logical_model_match = unreported）= INSUFFICIENT
verdict_validation  VALID | INVALID | NOT_REACHED
                    按 §6.5.2 校验；probe 与未达 PROVEN + SUFFICIENT 的 attempt 恒 NOT_REACHED；秘密泄漏命中 = INVALID
```

本表定义**单次调用**的判定；attempt 级三维 = 各次调用判定的保守聚合，唯一规范见 §6.6「调用组」（R22-B2 整改）。

**状态转换固定表**（按三维组合四行互斥且穷举，实现不得为未列组合自选状态；覆盖 probe 与 review 两种 attempt 模式，补发是 review attempt 内部调用、不另列；能力证据只取 §6.6「先按 `mode` 判来源」所列三条路径：review 成功的 tracked Receipt、probe 成功的 diagnostics Receipt、INVALID-但-PROVEN+SUFFICIENT 的 review 的 diagnostics Receipt）：

| call_path_proof | profile_binding | verdict_validation | attempt 结果 | 精确 Profile 后续状态（建议值） |
|---|---|---|---|---|
| `PROVEN` | `SUFFICIENT` | `VALID` | review：受治理判词 + 完整 Receipt（`governed_verdict`；含经补发后校验 VALID 的情形）；probe 不可达此行（`verdict_validation` 恒 `NOT_REACHED`） | `REVIEW_ENABLED` |
| `PROVEN` | `SUFFICIENT` | `INVALID` / `NOT_REACHED` | 只产 Receipt，无判词 | `PROBED` |
| `NOT_PROVEN` / `INDETERMINATE` | 任意 | 任意 | 只产 Receipt | 不高于 `UNVERIFIED`；环境仍完整时可保留 `CONFIGURED` |
| `PROVEN` | `MISMATCH` / `INSUFFICIENT` | 任意 | 只产 Receipt | 请求的精确 Profile 不得标 `PROBED` 或 `REVIEW_ENABLED` |

**契约版本与能力解耦**（gov-t8:OD-02 其三）：本设计的修订标识与设计文件 SHA-256 只作为事实记入 Receipt 与 effective Profile；继承读端不比对它们。理由：档案库以 `CONTRACT_FROZEN_SHA256` 钉扎 Profile 快照，每次 amendment 使全部既有快照不可继承、跨 amendment 复审须人工重选，是治理开销的主要来源之一（档案库台账第 3 类问题）。Profile 快照的可继承性由 `profile_schema` 版本号与治理链锚定（§6.9）保证；设计修订若改变 Profile 形状即换号，旧快照按号拒绝，与设计哈希无关。

**聚合商正式档**：直接接口适配器下应答体携带模型标识，`logical_model_match` 可判 `exact | registered_equivalent`，`profile_binding` 可达 `SUFFICIENT`，聚合商 Profile 可产出受治理判词（档案库 KB-07「聚合商只能 probe」的处置）；调用工具适配器下应答侧模型不可见时照旧 `INSUFFICIENT`，不放宽。`registered_equivalent` 必须在付费调用前登记，不得事后追加解释；`upstream_route_visibility = unreported` 不使 attempt 失效，Receipt 记 `route_provenance = unverifiable`。

### 6.12 逐条处置与决定文件（Amendment 4）

Owner 对一轮判词逐条 finding 的处置决定自 Amendment 4 起有机读承载（Owner 裁定 F6 甲、F7 甲）：**决定文件** `decisions.json`，由子命令 `respond` 写入并校验；r<N+1> 请求件的整改声明与已接受残留由通道据其派生并核对，执行者不再手写处置结论。决定权恒在 Owner：判词内不新增评审方的处置建议字段（§13 Y）。

**落点** = `attempt_round_dir/decisions.json`（§8.1：subject 轴 `review-attempts/<subject>/r<N>/decisions.json`，任务轴 `tasks/<task_record>/attempts/<stage>-r<N>/decisions.json`），轮级、不属任一 attempt；本地暂存层，永不入 Git（布局权威 §7 既有排除项，`task.template.md` 引导块的 `attempts/` 永不跟踪（原 task-artifact-schema §8.1））。其内容经 r<N+1> 请求件的派生段与任务书第 3 节的决定摘要进入证据链。

**形制** `decisions_schema = "review-channel-decisions/v1"`（封闭对象）：

```text
decisions_schema   固定 "review-channel-decisions/v1"
subject / stage / round / task_record   与被处置判词所属评审请求逐字相等；四成员恒在场，task_record 任务轴取 task record ID、subject 轴取 null（落点派生同 §8.1）
verdict_sha256     被处置判词（原 tracked_round_dir 内当前已发布文件或 §8.5 验证的历史原件）字节的 SHA-256；由通道填写
decided_at         ISO 8601 时刻；由通道填写
decisions[]        {finding_id, action: approve | fix | skip, instructions, work_item, owner_verbatim}
```

**动作闭集语义**（F7 甲；与后续审阅页面的三单选逐字对齐，本设计不实现页面）：`approve` = 认可该 finding、按其 `summary` 整改，`instructions` 可空；`fix` = 认可并按 `instructions`（必填非空）整改；`skip` = 本轮不处置，该 finding 转入下一轮 `accepted_residuals`。`approve` 与 `fix` 的差别只在是否附指令。`instructions` 在场时须为字符串；`work_item` 只允许在 `skip` 项在场（其他动作带 `work_item` 即拒）。

**校验规则**（`respond` 与 r<N+1> preflight 共用同一函数；任一不成立即 `decisions-invalid`，报告逐条列出）：其一，`decisions[].finding_id` 集合恰等于该轮判词机读块 `findings[].id` 集合（缺一、多一或重复即拒）；其二，`action` 在闭集内，且 `fix` 项的 `instructions` 必填非空；其三，`severity = blocking` 的 finding 取 `skip` 时 `work_item` 必填，文法 = 台账项 id `^[a-z0-9-]+:(OD|KB)-[0-9]+$`（非 blocking 的 `skip` 可选）；其四，`owner_verbatim` 必填非空，任何环节不改写、不摘要；其五，`verdict_sha256` 等于该轮已发布判词的字节身份（绑定被处置的那一版判词）。已写入的决定文件另核封闭对象形状（八个成员恒在场、无未知成员、`decisions_schema` 等于常量、`subject` / `stage` / `round` / `task_record` 与被处置轮相等、`decided_at` 非空、`verdict_sha256` 合 64 位小写十六进制文法），形状不符与其一至其四同码 `decisions-invalid`。

**`respond` 子命令**：`respond --decisions <决定输入绝对路径>`，零提供方接触、不是 attempt、不产 Receipt、不取同轮文件锁。输入 = 决定文件候选（含 `subject` / `stage` / `round` 与 `decisions[]`；`task_record` 任务轴必填、subject 轴可缺席；`decisions_schema` 可选、在场须等于常量；`verdict_sha256` 与 `decided_at` 由通道填写，输入内在场即拒；其余成员即未知成员、拒）；通道按 §8.1 派生两个目录值，要求原 `tracked_round_dir` 的该轮已发布判词与同轮 `receipt-r<N>.json` 同时在当前落点在场，或按 §8.5 来自同一可验证历史轮来源、两件均可严格解析且 Receipt `verdict_sha256` 等于判词字节的 SHA-256（任一不成立即拒：未发布的轮无从处置），取判词机读块 `findings[]`，按上列其一至其四校验，以「临时文件 + 同目录 rename」原子写入 `attempt_round_dir/decisions.json`（已存在即整体覆盖，覆盖前的字节不保留：决定文件是 Owner 当前决定的载体、不是历史记录）。stdout 恒为一个 JSON 报告对象：写入成功时 `{mode: "respond", state: "WRITTEN", decisions_path, decisions_sha256, verdict_path, verdict_sha256, next_round: {remediation_statement: <处置段>, accepted_residuals: [<派生残留项>]}}`，处置段与派生残留项只在 `next_round` 成员内、不作裸文本输出，供 caller 逐字粘入 r<N+1> 请求件；拒绝时 `{mode: "respond", state: "REJECTED", failure_code: "decisions-invalid", problems: [<逐条>]}`，stderr 同列问题项。`decided_at` 由通道每次取写入时刻，故每次 `respond` 都改变决定文件字节与其 SHA-256（处置段首行随之变化）：caller 恒以最近一次 `respond` 输出的 `next_round` 起草请求件，再次 `respond` 后须重新粘入，否则 r<N+1> preflight 判 `decisions-mismatch`。退出码：`0` 写入成功、`1` 校验拒绝或判词 / Receipt 不可定位、`2` 内部异常（§5.3）。

**派生与核对**（r<N+1> preflight）：其一，读上一轮 `attempt_round_dir/decisions.json`（上一轮 = `previous_round` 所指、该 stage 最近一轮已投递的轮）：缺席即 `decisions-missing` 拒绝（r2+ 恒要求决定文件在场；review-skip 后再开启评审的轮以最近一轮有效判词的决定文件为准，§6.9），不可严格解析即 `decisions-invalid`；其二，按封闭对象形状与上列其一至其四重校验（以上一轮判词机读块 `findings[]` 为对照），任一不成立即 `decisions-invalid`；其五不成立（`verdict_sha256` 不等于 `previous_round.verdict_path` 字节的 SHA-256）即 `decisions-mismatch`；其三，**处置段** = 通道以固定形制渲染的文本：首行 `Dispositions (decisions.json sha256 <前 12 位>)`，随后每条 finding 一行 `- <finding_id>: <action>`，`fix` 项后接 ` · <instructions>`，`skip` 项在 `work_item` 在场时后接 ` · <work_item>`，行序 = 判词 `findings[]` 次序；请求件 `review_brief.remediation_statement` 须以该段逐字起始，其后为 caller 追加的整改叙述，不满足即 `decisions-mismatch`（首行内的 SHA-256 前 12 位取自决定文件当前字节，以过时的 `respond` 输出起草即失配）；其四，**派生残留项** = 每个 `skip` 项各一条 `{id: RES-<n>, text: <finding title> · <work_item>}`（无 `work_item` 时 text 为 title），`n` 自 1 起按判词 `findings[]` 次序连续编号；请求件 `review_brief.accepted_residuals` 须逐字含全部派生残留项（id 与 text），caller 追加的残留项自其后续编，缺一或不等即 `decisions-mismatch`；其五，Receipt `decisions_sha256` 记该决定文件字节的 SHA-256（§6.6），任务书第 3 节渲染决定摘要（§6.3）。派生只读决定文件、不读 Owner 会话记录；`owner_verbatim` 只进任务书摘要，不进请求件。

**边界**：决定文件的写入口在本修订内只有 `respond` 终端形态；审阅页面与反馈队列作为其另一写入口时沿用同一文法（§16 不决定）。决定文件不入 Git，其丢失只使 r<N+1> 无法送审（`decisions-missing`），Owner 重新 `respond` 即可恢复，不影响任何已发布证据。

## 7. 评审方运行时适配层

### 7.1 适配器接口

```text
输入   封存后的被审输入目录（只读）· 评审方指令文本 · effective Profile · 秘密句柄（仅进程内）· attempt_options
输出   final_message（评审方最终消息全文）· runtime_evidence（事件计数、usage、请求 id 计数，无果记 unknown）
       · identity_claim（应答侧模型标识，无则 unreported）· process（exit、timed_out、stderr 摘要）
       · tool_version | endpoint_id · diagnostics（原始事件流路径等，落 attempt 目录）
义务   零秘密落盘；子进程或请求不继承父进程环境；不做任何改选或重试
```

适配器由 Registry `providers.<id>.runtime` 选定；契约层只经此接口调用，不认识具体适配器。

### 7.2 codex 命令行适配器（档案库 runner 设计 §6 至 §8 隔离语义的全文承载）

以下是该调用工具的专属知识，只住本模块：

- **进程环境从空构造**：`PATH` = 系统目录 + codex 可执行文件所在目录；`HOME`、`TMPDIR`、`CODEX_HOME` 均指向本次 attempt 的临时目录（阻断用户级配置、规则、插件、MCP、记忆与 instruction 发现）；只注入当前 Profile 的一个 key 变量名（builtin-native 不注入任何 key）。
- **生成的临时配置**（隔离 `CODEX_HOME` 内）：`model`、`model_reasoning_effort` 一等字段；official-direct / aggregator 写 `[model_providers.<id>]`（`base_url` = 解析所得端点值、`env_key` = key 变量名、`wire_api` = transport）；builtin-native 不写 provider 块（走内建后端，认证由隔离副本承载）；`[shell_environment_policy] inherit = "none"`；`[tools] web_search = false`；不写任何 MCP、plugin、hooks、memories、rules、notify 配置。端点值只在临时配置文件中，用后删除。
- **调用形态**：`codex exec --strict-config --skip-git-repo-check --ephemeral --ignore-rules --sandbox read-only --color never -C <封存目录> --json -o <最终消息文件> [-c key=value …] "<指令>"`，指令走参数，stdin 钉死 `/dev/null`，不 resume、不续接。
- **受治理保护的 override 前缀**（命中即 preflight 失败）：`model`、`model_provider`、`model_providers`、`model_reasoning_effort`、`shell_environment_policy`、`sandbox`、`sandbox_permissions`、`approval`、`approvals_reviewer`、`mcp_servers`、`hooks`、`plugins`、`rules`、`memories`、`features`、`notify`、`history`、`projects`、`experimental`、`profile`、`profiles`、`tools`、`web_search`。builtin-native 不接受任何 override（非空即拒），`effort` 一等字段不受此限。
- **识别探针**（override 可识别性的零费用证明）：进程内起回环 HTTP 应答器（恒回 401），以真实生成的配置形状（base_url 指向应答器、key 为哑值、附全部 override）spawn 一次；配置装载报错 → `runtime-key-unrecognized` 拒绝；应答器收到请求 → 识别通过；两者皆无 → `runtime-recognition-indeterminate` 拒绝。builtin-native 无 base_url 重定向形态，探针不可构造，记 `not-applicable-builtin-native`。
- **builtin-native 认证六条**（档案库契约 §7.3 的全文承载）：其一，认证正本 = Registry `auth_source` 所指用户级登录态文件，只读复制进隔离 `CODEX_HOME`，权限 0600，随 attempt 临时目录销毁，绝不写回、用户级目录零写入；其二，复制前对读得字节按 `present | missing | malformed` 三态重验（先验后写），低于 `present` 即以独立失败码 `auth-source-missing-at-staging` / `auth-source-malformed-at-staging` 中止、不 spawn、不留副本；其三，认证载荷整体是秘密：解析副本并把全部长字符串叶值与键名含 token / key / secret 的字符串值并入本次 attempt 的扫描集（§7.5）；其四，preflight 只报告三态，不显示内容、长度、前后缀或摘要；其五，令牌刷新可能使用户正本失效，属披露残留，禁止以写回消除；其六，Receipt 与 Profile 只记路径名与 `auth_mode`，不记内容哈希或可逆摘要。评审方工具子进程理论上可读隔离副本，出口侧通道只机械覆盖它捕获的输出面（全量扫描 + Web 检索关闭），其他出口属沙箱行为（§15）。
- **三维判定的观察点**：进程 exit 0 且最终消息非空 → `PROVEN`；进程失败或超时 → `NOT_PROVEN`，按 stderr 关键词分类为 `provider_unavailable` / `authentication_failed` / `runtime_rejected_config` / `timeout_or_transport_failure`；exit 0 但空输出 → `INDETERMINATE`。事件流（`--json`）的用量、请求 id 与计数先尝试提取，无果才记 `unknown`；应答侧模型标识本路径不可见，aggregator 恒 `INSUFFICIENT`。

### 7.3 Anthropic 模型评审路径：三候选探针（gov-t8:OD-02 其九；R1-B9 整改）

Owner 裁定三候选设计期探针后定取舍。本设计冻结**每条候选的探针问题、证据字段与判据**，以及比较后呈 Owner 的决策输入形态；具体命令行参数或请求体细节由探针结果填入本节并作为本设计 amendment 输入。

| 候选 | 探针问题 | 证据字段（落 `records/diagnostics/review-channel/<日期>/`） | 判据 |
|---|---|---|---|
| A · `claude` 命令行 | 能否一次性会话、不持久化、不读用户级配置与规则（隔离配置目录）；工作目录 = 封存目录时工具面是否只读且无网络、无写入；指令走参数或标准输入时是否会等待附加输入；最终消息能否捕获为文件；认证（API key 或登录态）是否进入工具子进程环境；在四道门同款净化启动与沙箱下 Keychain 是否可达（档案库 OD-149 已知坑） | 各问题的实测命令、退出码、stderr 摘要、环境变量与文件系统差异清单、工具版本 | 全部问题满足 §7.1 义务即「可用」；任一不满足且无配置可关即「不采用」 |
| B · Anthropic messages 直接接口 | 内联投递下典型被审输入（本设计自身的 impl 轮）是否在 `max_input_bytes` 内；结构化输出是否可约束 §6.5.1 机读块；应答体是否携带模型标识；费用与时长 | 请求体形状（去密钥）、应答头与用量、`logical_model_match`、时长 | call-path `PROVEN` 且机读块校验 VALID 即「可用」 |
| C · codex 自定义 provider 接 Anthropic 的 OpenAI 兼容端点 | codex 以 `wire_api = chat` 对该端点是否可完成一次评审运行；只读沙箱与零继承是否照旧；应答侧模型标识是否可见；与候选 A / B 相比是否多出配置面 | 同 §7.2 的 Receipt 字段 | 同 B；另须 transport `chat` 在 codex 适配器声明的支持集内 |

比较后呈 Owner 的决策输入 = 三行结果表 + 推荐；Owner 裁定后 Registry 登记被采用候选的 provider 条目（runtime、transport），未采用者不登记。Definition Acceptance Criteria 第四条的二选一形态由此承载：真实运行证据（被采用候选的首次受治理评审）或探针证据 + Owner 裁定。至少一条候选可用是硬约束（Goal Conditions 第五条）；三条皆不可用属 HUMAN 停报。

### 7.4 直接接口适配器（gov-t8:OD-02 其十三）

通道自身经 HTTP 调用模型提供方接口，不经任何调用工具。三种协议一个模块内分函数承载：OpenAI 兼容 chat completions（DeepSeek Official、Zhipu GLM Official、SiliconFlow、OpenRouter 等均支持）、OpenAI responses（OpenAI 官方）、Anthropic messages。

- **投递形态 = 内联单次调用**：通道把被审输入逐件以定界段（投递名、字节数、SHA-256、内容）拼入用户消息，任务书在前、被审对象次之、参考件在后；指令注入为系统消息。评审方无文件工具：`scope_files_read` 由评审方按实际阅读自报（投递名集合子集），`tools_used` 必须为空数组，Receipt `delivery = inline` 记录投递形态（§6.5.2 第 9 条）。
- **容量守卫**：投递总字节数与 Registry `max_input_bytes` 比对，超限 preflight 拒绝（§6.2 第 7 条）；不做分片，分片会破坏「被审输入即全部输入」的封闭性。
- **单一输出模型**（R1-B10 整改）：直接接口路径下评审方的最终消息恒为一个 JSON 对象 `{machine: <§6.5.1 机读块对象>, narrative: <Markdown 叙述正文字符串>}`；Registry `structured_output = json_schema | json_object` 时以提供方结构化输出约束该形状，`none` 时以指令要求该形状并对文本做 JSON 解析。通道把该对象确定性渲染为严格发布文法的判词（按 §6.5.3 span 提取算法取得的 `machine` 原样 JSON 字节区段 + 解码后的 `narrative`），`narrative` 须满足 §6.4 叙述约定并经 §6.5.2 第 13 条核对；对象不可解析或形状不符即 INVALID、分类 `reviewer_output_invalid`，**本路径不自动补发**（R2-B8 整改：叙述正文在 wrapper 内是字符串而非独立行，§6.5.4 的恢复算法不适用；Amendment 2 的两类触发在本路径均不适用；下一 attempt 按 §6.7 规则 7 由 caller 归因后发起）。「最终消息即判词」在本路径的含义 = 该对象是判词的唯一来源，通道只做形态渲染不改值。
- **身份证据**：应答体的模型标识进入 `identity_claim`，聚合商据此可判 `logical_model_match`（§6.11）。
- **秘密**：key 只在进程内内存，请求头由适配器构造；base URL 由 `base_env` 解析（§7.5）；响应体落盘前过秘密扫描。
- **重试**：适配器不做重试（继承 no-fallback 与「失败即汇报」）；HTTP 层的单次请求即一次 attempt，`request_count` 恒 1（本路径下「一个 attempt 不等于一次请求」的残留消失）。
- **KB-37 残留在本路径消失**：无工具循环，「运行时接受配置却不遵守」的观察面只剩 model 与 effort 的实际执行，与 operational claim 同级（§15）。

### 7.5 秘密边界（档案库契约 §7 与 runner 设计 §6 的全文承载，扩展至新提供方）

- **配置正本** = `~/.zshrc` 中 `export NAME=<literal>` 形态的环境变量声明。通道以非执行解析器读取：不调用 zsh / bash、不 `eval`、不 `source`、不生成可执行临时脚本；只接受当前 Profile 在 Registry 声明的精确变量名，每个名字必须唯一出现为整行 `export NAME=<literal>`；`<literal>` 只允许裸字面量（字符集 `[A-Za-z0-9._:/~%-]+`）、单引号串（内部无 `'`）、双引号串（内部无 `$`、反引号、`\`）；parameter / command / process / arithmetic substitution、glob、重定向、管道、控制运算符、函数、alias、行接续、行尾注释与重复声明一律 fail closed。preflight 只报告 `detected_literal | missing | duplicate | dynamic_rejected`，不显示值、长度、前后缀或可猜测摘要；解析失败不回退到父进程同名变量、其他 startup 文件或硬编码端点。新增提供方（如 `ZHIPU_API_KEY` / `ZHIPU_API_BASE`、`ANTHROPIC_API_KEY` / `ANTHROPIC_API_BASE`）只是 Registry 条目，解析器不改。
- 秘密解析在所有模式下（含 standalone preflight）都是硬性通过条件。
- 解析结果只进入从空环境建立的适配器执行上下文（子进程环境或进程内请求头），除选中的 key / base 外只注入显式允许的无秘密运行变量；父进程其他环境不继承。
- builtin-native 与 claude 登录态：认证文件三态、先验后写、扫描集扩展、写回禁令按 §7.2 六条同款处理；认证文件路径名由 Registry `auth_source` 声明。
- **落盘前秘密终检**：全部持久 artifact（判词、Receipt、effective Profile、诊断层）先在内存内构造并扫描；命中已解析的 key / 端点值或认证载荷扫描集中的任一值——无论出现在评审方输出还是请求侧证据字段——该 attempt `verdict_validation = INVALID`、判词不发布，泄漏内容以 `[REDACTED-SECRET]` 替换后只留诊断与 Receipt 事实（`secret_leak_redacted` / `secret_leak_in_evidence` 分别记录）。
- 秘密值与端点值绝不进入命令行、评审方指令、被审输入、事件流、判词、Receipt、异常文本或 Registry；允许记录变量名与非秘密端点身份哈希。

### 7.6 运行时版本：只记录（gov-t8:OD-02 其十四）

每个适配器把每次调用的运行时版本（命令行工具的 `--version` 输出；直接接口为端点标识与应答头中的版本信息）写入该次调用的 `calls[]` 项；Receipt `runtime` 组按 §6.6 确定性表示取首次调用值并记 `changed_within_attempt`（R25-B1 整改）。通道不比对、不报告差异、不提醒、不降级、不重绑定；`changed_across_rounds` 按 §6.6 四情形总函数机械填值（继承与显式改选一体适用，R27-B1 整改），是可见事实不是判定。能力绑定元组不含版本（§6.11）。

### 7.5 产品 ExecutionPort 与外部 Host（H-04/H-09/H-10/H-14/H-16/H-17）

Registry 增加外部执行端口的明确登记：端口身份、运行模式 embedded/standalone、profile id/version/digest、purpose、provider/model/transport/effort、模型厂商与路由来源、批准语义，以及可核验能力 Receipt。原 provider 内部适配器解析仍服务维护模式；产品 embedded 接口由 Host 注入 ExecutionPort，不从被审仓根寻找另一个 Agent 可执行物，也不再直接 spawn。standalone 由 LocalExecutionPort 提供同一职责。两种入口的资格独立建立，问答可用、原生登录、CONFIGURED 或另一入口的 Receipt 不等于当前端口 REVIEW_ENABLED。

同一物理请求的持久身份是 `executionRequestId`，绑定 resource、domain operation/node、控制代次、executionBinding、profile 与输入摘要。先 preflight，再持久预约、请求启动并核对放行；应答丢失 query 原请求，不新建执行。等待是异步的，operation/query/cancel 仍可响应；排队与背压不是 Reviewer FAIL。`sealDir` 是通道封存材料的只读目录，`instructionText` 是通道生成的指令原字节，作为内部端口调用的正式参数，由 Runtime 转为 Contract 允许的资源引用和输入；不得把任意绝对路径直接发给 Host，回答原字节回 hp 校验，Host 不代产 Verdict。

模型厂商由 hp 的 VENDORS 所有者维护登记映射，未知模型或集合拒绝。映射核对实际 `actualBinding.model` 与已登记提供方，不以 caller自报或路由名代替；例如 `claude-opus-5[1m]` 的实际模型后缀与 Contract 引用 `claude-opus-5:1m` 是两种身份表示，按登记关系匹配，不凭字符串去掉后缀猜模型。Reviewer 厂商必须不在完整作者集合中。

J-04 Assistant输入固定为 `host-execution-facts-j06.md` r2 附录A：端口 embedded；Implementer profile `coding-implementer/claude-print-restricted` v1，digest `2c9583da0f4101cc04e86251d85ba15c3a2bc9d6fda024f8d79081566744f16c`、purpose coding-implementer、approval auto-deny；Reviewer `review/codex-native-readonly` v1，digest `c30bd24676b535c1e1422a58c686a2edb7a4a7719fcd9b912119f161744792ce`、purpose review、approval expected-range-gate；该 Reviewer 策略在附录 A 策略字节之外只多受限设置 `skills.include_instructions = false`（Codex 0.159 起即使跳过主机技能发现，仍把每个可发现技能的名称、描述与路径写进模型指令，该设置把技能清单留在请求之外），id 与 version 不变。旧 Implementer `5bb50653…` 与旧 Reviewer `8061614d…` 不可登记；programIdentity 每次重新发现实际安装，不写版本允许列表，不因版本变化永久禁止兼容组合；变化后重核受影响资格证据。profile信任边界、用途、执行端与批准事实随 Receipt 保存，秘密不进入领域。

round lock 只防同轮的并发通道操作；取锁到原件/Receipt结算均由显式上下文负责，正常、异常和取消在 finally 释放，inode不删除不替换。进程死亡自然释放 round lock 不解除领域writer锁语义或物理预约；Agent仍活着/状态未知时，不得以重新取得round lock为由重复调用。Standalone LocalExecutionPort 与 embedded 同样核对物理退出证据。

最低验收：长寿命worker连续attempt可重取锁、同轮竞争拒绝且inode恒定；取消/端口异常可持久化且不耗补发预算；未放行、已放行结果未知、实际成功非空/成功空/失败分别覆盖，单纯接收或放行不可产生PROVEN或资格；未知物理结果query同请求且继续预约保护；首次PROVEN后故障聚合不得抬升；畸形前轮引用失败Receipt可归档；不合模板Definition零provider调用；精确J-04元组通过与逐字段错误拒绝；Host/CLI交叉资格不能互认；启动应答丢失query同请求；hp退出而Agent未退出不能再执行；无真实资格时只能报告未验，不能用fake提升REVIEW_ENABLED。

## 8. 落点、四件最低成员与证据衔接

本章 §8.1 至 §8.5 先保留 legacy-git 的精确发布与恢复契约；archive-v1 的物理存储、并发及成功判据以 §8.6 逐项替换，不调用旧 tracked 目录晋升步骤。

### 8.1 落点派生

| 产物 | 落点 | 层 |
|---|---|---|
| 任务书（`review-task`） | `tracked_round_dir/HarnessPlane_<Subject>_Review_Task_R<N>.md` | 入仓永久层 |
| 判词 | 同目录 `HarnessPlane_<Subject>_Review_R<N>.md` | 入仓永久层 |
| 被审输入清单 | 同目录 `bundle_manifest.json` | 入仓永久层 |
| Receipt | 同目录 `receipt-r<N>.json`（从 attempt 目录 exact copy，通道执行） | 入仓永久层 |
| 评审请求、封存副本、原始最终消息、运行事件流、stderr、effective Profile 文件、补发调用的原始消息与运行证据（`reemit-` 前缀） | `attempt_round_dir/<attempt_id>/` | 本地暂存层（永不入 Git；两轴的根均为布局权威 §7 冻结的 `.gitignore` 排除项） |
| 决定文件 `decisions.json`（§6.12，Amendment 4） | `attempt_round_dir/decisions.json`（轮级，不属任一 attempt） | 本地暂存层（永不入 Git） |

**两轴落点派生**（R2-B3、R3-B3 整改；布局权威 §7 两轴分流）。最小可路由解析（§6.1）通过后，通道**一次派生两个目录值**，此后本设计所有规则（任务书生成、清单、封存、文件锁、早期 Receipt、轮次计数、暂存与提交、清理、补发）只消费这两个值，不再各自拼路径：

```text
axis               = task_record 在场 ? task : subject
tracked_round_dir  = task ? tasks/<task_record>/reviews/<stage>-r<N>/   : reviews/<subject>/r<N>/
attempt_round_dir  = task ? tasks/<task_record>/attempts/<stage>-r<N>/  : review-attempts/<subject>/r<N>/
tracked_parent     = tracked_round_dir 的父目录（同轴同 stage 的轮目录集合所在处；subject 轴不带 stage 前缀，stage 只入清单字段）
```

文件名中的 `<Subject>` 由 subject 转写；attempt 目录 = `attempt_round_dir/<attempt_id>/`。四件最低成员的文件名、角色与「判词由通道直接发布、Receipt exact copy」自减重第 5 步起由本节自承载（原沿 task-artifact-schema §10.2，取值零变化）；本设计不新增 tracked member，补发调用的产物全在本 attempt 的暂存目录，其事实由本轮 Receipt 的 `extraction` 与诊断层摘要承载。

### 8.2 发布次序

attempt 生命周期内的产物次序（R1-N4 整改）：① attempt 目录建立（§6.1 最小可路由解析后）；② 封存：候选与参考件复制进 attempt 目录并置只读，再从封存副本计算预清单、渲染任务书、计算最终清单（§6.3 次序；此时 `tracked_round_dir` 不存在）；③ 调用；④ 治理 artifact 内存内构造并过秘密终检；⑤ 诊断层落盘（attempt 目录）；⑥ **tracked 目录提交协议**（R2-B2 至 R11-B2 整改；依赖同文件系统内 `rename` 的原子性——attempt 目录与 tracked 目录同属本仓工作树）。

**威胁模型（显式；R12-B2 整改后的保证面）**：本协议保证的对象是——**同一工作树内**并发运行的其他通道进程、本通道进程的崩溃遗留、以及 `tracked_round_dir` 上预先存在的任何目录；本协议**不保证**的对象有二：其一，同一工作区内非通道进程在协议执行期间对 `tracked_parent` 下目录的改名、替换或写入——与直接编辑证据文件同级，属越界写入，由 Git 历史与 Owner 合并审查事后暴露（`locks` 门 evidence 登记已随减重第 2 步退役）；其二，**跨 worktree 的同轮互斥**——各 worktree 的工作区目录项互不可见，本协议的文件锁与目标核对都只在本工作树内有效。跨 worktree 的同任务轮次不需要通道互斥：`D-09@r1` 第 1 条把每任务钉为「一 worktree、一任务分支、一执行会话」且「一 worktree 任一时刻至多一个实际写者」，同一 task record 在两个 worktree 各起 attempt 本身已违反该形态；subject 轴（`reviews/<subject>/r<N>/`）跨 worktree 同轮的可能性由 MR 合并时的同路径冲突暴露、Owner 裁定，登记为残留（§15）。通道不为两类不保证对象提供机械防线（与四道门对工作区并发编辑的态度一致）。

**原语选择与两条铁律**：其一，通道**从不在目标路径上创建目录，从不接管、删除、改写目标路径上预先存在的任何目录，rename 之后没有任何触碰 tracked 目录的动作**——不存在「补完成」「恢复」一类对 tracked 目录的写入；其二，**发布 = 一次 `rename`**：完整的四件轮目录先在 attempt 目录内暂存好，`rename` 成功即发布完成，tracked 目录自出现之刻起恰为四件。`rename` 对非空目标恒失败（`ENOTEMPTY` / `EEXIST`），对空目标会替换——故 rename 之前先核目标不存在，目标存在（无论空或非空、无论内容）即拒绝；替换空目标的情形只可能由威胁模型外的非通道进程在核对与 rename 之间制造（§15 残留）。

**状态与动作**（`name` = `tracked_round_dir` 的末段；`parent_fd` = `os.open(tracked_parent, O_RDONLY | O_DIRECTORY)`；暂存目录 = `attempt_round_dir/<attempt_id>/publish.tmp-<attempt_id>/`）：

1. **暂存**：在 attempt 目录内建立暂存目录；把任务书、清单、判词三件从 attempt 目录 `os.link` 进暂存目录（attempt 目录保留原件）；把成功 Receipt 的字节写为暂存目录内的 `receipt-r<N>.json` 并 fsync 目录。暂存目录恰四件。**位置定义**：`publish.tmp-*` 内的文件不构成 Receipt 或任何治理事实（§6.6「Receipt 的身份由位置承载」），它们是即将 rename 的过渡内容，失败即整体删除。
2. **目标核对**：`os.stat(name, dir_fd=parent_fd, follow_symlinks=False)` 须为 `ENOENT`；目标存在（任何形态）→ 失败码 `tracked-round-dir-occupied`，转第 4 步。报告中如实描述所见形态供 Human 处置——四件齐备（已发布轮，本轮不应再投递）或其他（预先存在的目录或越界写入，通道不代为清理、不代为判定归属）。
3. **落位**：`os.rename(staging_dir, name, dst_dir_fd=parent_fd)`（同文件系统内原子）；成功即发布完成，tracked 目录恰四件；失败（`ENOTEMPTY` / `EEXIST` 等，含并发通道进程先落位）→ 失败码 `publish-rename-failed`，转第 4 步。
4. **失败终态**（第 1 至 3 步任一失败）：整体删除本 attempt 的暂存目录（在 attempt 目录内、由本进程创建）；在 attempt 目录写失败 Receipt `receipt.json`（`verdict_published = false`、`verdict_validation = INVALID`、分类 `reviewer_output_invalid`、失败码如上）。tracked 目录未被触碰。每个 attempt 因此恰有一份可观察的 Receipt。
5. **回链（发布后的诊断层动作，不触碰 tracked 目录）**：rename 成功后 `os.link(tracked_round_dir/receipt-r<N>.json, attempt_dir/receipt.json)`，使 attempt 目录持有与 tracked Receipt 同 inode 的副本；链接失败只在 stderr 报告 `receipt-backlink-failed`，发布事实不受影响（tracked Receipt 即本 attempt 的 Receipt）。attempt 目录缺 `receipt.json` 的已发布 attempt，由下一次 preflight 从 tracked 目录再次硬链接补齐（同 inode，读取 tracked 目录，不写入；Amendment 4 前 `register` 亦执行此动作）。
6. **崩溃遗留与 Receipt 总量性（preflight 前置，R12-B1、R13-B1、R13-B2 整改）**。**进程代际身份**：`attempt.json.pid_start` = 进程启动时间令牌——Linux 取 `/proc/<pid>/stat` 第 22 字段并附 `/proc/sys/kernel/random/boot_id`，macOS 取 `sysctl kern.proc.pid.<pid>` 的 `p_starttime`（或 `ps -o lstart= -p <pid>` 的字面串）；「不存活」⇔ 同 pid 的进程不存在、或其启动令牌与记录不等（pid 已被复用）、或其状态为僵尸（Linux `/proc/<pid>/stat` 状态 `Z`，macOS `ps -o stat=` 首字符 `Z`）；令牌无法取得时**保守视为存活**、不补产、只报告 `liveness-undeterminable`。**动作**：对 `attempt_round_dir/*/` 内每个「`attempt.json` 在场、`receipt.json` 缺失、所记进程不存活」的 attempt：其一，若 `tracked_round_dir/receipt-r<N>.json` 存在且其 `attempt_id` 等于该 attempt → 已在崩溃前落位，按第 5 步回链（`os.link` 自带 `EEXIST` 排他，先到者成功）；其二，否则**先写后链**（R14-B1 整改）：恢复者把补产 Receipt 字节完整写入同目录临时文件 `receipt.json.tmp-<pid>-<pid_start>` 并 fsync，再 `os.link(tmp, receipt.json)`——`link` 原子且对已存在目标恒 `EEXIST`，最终路径因此要么不存在、要么是完整字节；成功后 unlink 临时文件；`EEXIST` 者（另一恢复者已链接，或原进程恰在此刻写出）unlink 自己的临时文件后退出、不改动任何内容。临时文件由其名内所有者清理，所有者不存活时由前置清理。其三，**`publish.tmp-*` 的清理与 Receipt 无关**：只要其所属 attempt 进程不存活即整体删除（它是暂存、从未落位、不是治理事实），不论该 attempt 是否已有 Receipt。补产 Receipt 因此对每个 attempt 恰有一份、一经可见即完整且不改字节；两个 preflight 并发恢复只有一个链接成功。`.alloc-*` 目录（§6.1）只在其名内所有者不存活时前置删除，它从未成为 attempt、无需 Receipt。全部切点由此都有终态：分配 rename 前崩溃 → `.alloc-*`（所有者已死）删除、无 attempt；分配后至发布 rename 前崩溃 → 暂存删除 + `interrupted` Receipt（字段随 phase 完整）；发布 rename 后回链前崩溃 → tracked 四件齐备 + 回链；恢复者在写临时文件后、link 前崩溃 → 临时文件（所有者已死）删除、Receipt 仍缺失、下一次恢复重做；恢复者在 link 后、清理暂存前崩溃 → Receipt 完整在场、暂存按其三规则删除。tracked 目录不存在任何「遗留态」：rename 之前 tracked 目录不存在，rename 之后即完整。

**目录形态不变量**（与 `task.template.md` 引导块的目录成员闭集对齐；原 task-artifact-schema §8.1 / §10.2）：`tracked_round_dir` 在任何时刻只有两态——不存在，或四件成员齐备（已发布轮）。通道从不产生零件或少于四件的 tracked 目录；预先存在的目录永不被通道改动。步骤 ③ 至 ⑤ 任一失败或判词校验 INVALID 时不进入本协议。

**Receipt 的真实性与总量性**：Receipt 的身份由位置承载——`tracked_round_dir/receipt-r<N>.json`（已发布轮）与 `attempt_dir/receipt.json`（本 attempt 的 Receipt；review 成功时是前者的同 inode 副本，probe 成功时是只存于 attempt 目录的 `receipt_only` Receipt（§6.6 `completed` 行），失败时是失败 Receipt，崩溃时是后续 preflight 补产的 `interrupted` Receipt）；暂存目录内的同名字节不是 Receipt。review 的成功 Receipt 因此只在 rename 成功后才作为 Receipt 存在；失败路径恰有一份失败 Receipt；崩溃路径在下一次 preflight 后恰有一份 `interrupted` Receipt 或一份回链；不存在「声称已发布而 tracked 目录无 Receipt」「一个 attempt 有两份 Receipt」或「已分配 attempt 永久无 Receipt」的可观察终态。补产是本设计中唯一由他进程为某 attempt 写 Receipt 的动作，其字段闭集见 §6.6 补产行：除 `synthesized_by` 与 `utc`（恢复事实）外全部取自 `attempt.json`，不含任何自述的成功；「临时文件写全 + hard link」使并发恢复者中恰一个链接成功。补发是 review attempt 内部调用：不分配 attempt、不产生第二份 Receipt、不向 tracked 目录发布任何成员。

**同轮并发防线（同一工作树内；R14-B2、R16-B1 整改）**：attempt 分配（§6.1）之后，在 `attempt_round_dir/.in-progress` 上取**建议性文件锁**——`os.open(path, O_RDWR | O_CREAT)`（无 `O_EXCL`：文件的存在不是锁）后 `fcntl.flock(fd, LOCK_EX | LOCK_NB)`。锁的载体是内核对该打开文件描述的排他锁，不是路径、不是文件内容：`EWOULDBLOCK` ⇔ 另一进程正持有 → 本 attempt 以 `preflight_failed` + 失败码 `round-in-progress` 产 Receipt 结束；持有者进程以任何方式终止（正常退出、崩溃、被信号杀死）时内核即释放，**不存在「死锁」概念，因而不存在存活性判定、清理、替换与隔离文件**（R15-B1 / R16-B1 的路径复用 ABA 与 R16-N1 的隔离遗留由此整类消失）。取得后持有者 `ftruncate` 并写入 `{attempt_id, pid, pid_start, at}` 供人读诊断，拒绝方可读取该内容写入 stderr 报告，但该内容**不是任何判定的输入**（可能陈旧或为空）。**锁的粒度是通道进程**（R17-B1 整改）：一个通道进程在其生命周期内至多打开 `.in-progress` 一次（第一个 attempt 分配之后），此后该进程内的全部动作（含 review 的补发调用）在同一持有下进行；flock 锁与打开文件描述绑定，同一进程再次独立 `open` + `flock` 在 Linux 上会与自身既有持有冲突，故通道禁止二次打开（自测静态断言）——「`EWOULDBLOCK` ⇔ 另一进程正持有」在此前提下成立，父 attempt 从校验到补发返回、不变性核对、发布的全程互斥不中断。释放 = 进程结束前 `close(fd)`；通道**从不** `unlink`、`rename` 或替换 `.in-progress`（该文件一经建立即与轮目录同寿，inode 在其后各 attempt 间恒定）。锁对象是 inode：同一工作树内的通道进程恒打开同一 inode，互斥成立；非通道进程删除或替换该文件属威胁模型外（其一）事件，登记为 §15 残留。**平台前提**：`fcntl.flock` 是 POSIX 原语，本设计运行时前提为 macOS / Linux（与第 6 步进程代际身份同一前提）；网络文件系统上的 flock 语义不在保证面（§15 残留）。落位 `rename` 对非空目标恒失败是第二道防线（下文）。跨 worktree 不在保证面（威胁模型其二）。

### 8.3 证据体积的处置（`legacy:OD-17` 甲案）

前序 legacy:OD-17 甲案不改留存面的决定属于当时历史；CL-52 按 spec FR-50 与布局 §7 新增有条件的 HEAD 退出。每轮首次发布入仓的仍是四件最低成员。体积下降来自三处：Receipt 不内嵌清单（每轮省一份清单）；任务书事实段由通道渲染（不再手抄整段格式契约与哈希，任务书缩短）；运行事件流与封存副本恒在暂存层（既有做法，本设计成文）。验收要求一次同类轮次的体积对照在案（Definition Acceptance Criteria 第五条）。

### 8.4 证据登记衔接（已退役，Amendment 4）

`register` 子命令、`--no-register` 开关与 `review` 成功后的自动登记自 Amendment 4 起退役（Owner 2026-09-06 裁定，台账 `repo-od-10:KB-08`）：其第二步调用的 `gates.py locks --record evidence` 已随减重第 2 步删除，证据登记本 `records/evidence-locks.jsonl` 为只读历史档案（`records/README.md`），该子命令自减重第 2 步起恒失败。通道自此在发布（§8.2 ⑥）之后不执行任何 Git 动作：四件最低成员的 `git add` 与提交均属 caller（D-08 工作分支常设授权）或 Owner；多轴并行投递不再需要串行补跑登记。评审证据入仓的字节完备性改由 MR 描述申报与 Owner 合并时的人工核差承载（`HANDOFF/README.md` 申报三）。原三步次序见 Git 历史（FROZEN r4）。

### 8.5 历史轮与固定输入读取（CL-52）

本节在 repo-layout §7.4 启用条件满足后适用；共同 helper 由该单元承载，本通道不建历史副本目录。`scan_rounds`、`check_round_sequence`、`round_budget`、`load_previous` 共用现存与有效定位历史的原轮路径视图。按原轴、subject/task record、stage、round 的既有逻辑识别，不以新物理目录重编号；task 与 impl 分开，subject 轴无 stage 路径前缀的序号空间保持。相同原路径同 blob 去重，冲突版本停报；目录退出不能归零额度、重新使用轮号或绕过 `review-skip` 裁定。

轮数计算保持原“已发布 Receipt 在场”判据，不因旧 Receipt schema 已不支持继承而少计历史轮。继承则严格核验原 Receipt 成功字段、Profile 全字段、subject/stage/round、清单 canonical hash、Verdict hash 和每件 candidate baseline 既有 SHA-256；Receipt、manifest、任务书、判词须来自同一完整轮来源 commit，禁止逐件从不同快照拼轮。现存与历史混合时仍须证明对应同一发布身份；不满足即拒绝。旧 schema 不兼容沿原继承拒绝，不自动升级或伪造 v2 Receipt。

§6.2 的候选永远来自当前工作树，不可历史回退；裸名域一/域二仍只按现行解析域，不扩展到全 Git 历史。请求 v4、Receipt v2 与 bundle manifest 闭集不加字段。`inputs.references` 与 `previous_round` 的原路径缺席时，可由有效定位文件唯一解析历史来源；无有效定位即原缺件错误，歧义拒绝。现有请求字段没有历史版本选择槽，因此同一路径多版本时该请求拒绝歧义；人工可用共同 CLI 的显式 source_commit 独立查询，但该输出不自动解除请求拒绝、不充作当前引用副本。未来若需在请求中选版本须另行修改请求契约，本批不引入 `commit:path` 新语法。既有显式 commit 的证据引用直接用固定来源读取。所有历史 bytes 仍经过同一秘密扫描、大小限制、封存与身份检查；来源路径保持原路径，不把暂存副本路径写成原源。

§6.3 生成任务书增加“历史来源”表，列恰为原路径、source_commit、blob_oid、sha256；仅列实际消费的历史输入，没有时明确无。来源表字节由既有任务书封存身份纳入 bundle 校验，不修改 manifest 成员文法。历史基线 `recover_baseline` 继续只按既有精确 SHA-256 从原 attempt 或 Git 搜寻；不把任意目录快照当作原候选。退出前必须证明每个所需旧候选可恢复，缺唯一原件则保留该组，不能清理 ignored 层唯一副本。

§8.2 的发布锁、存活性、generation、Receipt 完成前后的原子发布次序保持。`preflight_cleanup` 与 `publish` 在判定无已发布目标时都检查历史原轮存在性；已归档发布轮仍禁止覆盖与复用编号。在既有同轮互斥范围内，最终 rename 前重复核验来源视图未变；不能通过只看空的 tracked_round_dir 放行。崩溃恢复仍先判原存活性/generation 条件，若需回读已发布 Receipt，须从同一验证轮按 Receipt 的 attempt_id 精确回链，只在原 ignored attempt 层补齐既有允许的产物；不重建历史 tracked 目录，不接管其他轮或活动进程。

`run_respond` 按本节读取同一发布轮的判词与 Receipt 后沿 §6.12 校验和写入，决定文件仍仅在 ignored attempt 层，不从历史判词推导 Owner 决定。旧 decisions.json 缺失沿 `decisions-missing`；只有新的明确 Owner 输入才能通过 respond 重建当前处置，不把 Receipt 的旧哈希当作决定正文。

Registry capability 装载继续要求当前文件、固定 Git blob 与 Registry 哈希三方相等及祖先关系，§6.6 规则不放宽。当前 Registry 引用的 r31 四件等实际凭据保持在场；历史继承成功不证明当前 provider 可用，不触发探针或 provider 调用。

依赖 helper、来源对象或连续性证明缺失时，preflight 在 provider 调用前拒绝，沿既有 `preflight_failed` 分类、退出 1，新增 `failure_code = history-unavailable`，具体 helper code 写现有问题说明；该 failure_code 的闭集实现归施工时的通道 contract 更新，不新增 attempt 分类、请求或 Receipt 字段。没有定位声明的普通缺件与旧 schema 不兼容仍沿既有原错误。`respond` 保持 `decisions-invalid`、退出 1，并列来源原因；内部异常仍退出 2。独立 preflight 仍无 Receipt。不得以空历史、默用最新 blob 或自动联网修复继续评审。

### 8.6 本机耐久归档协议（CL-55 候选）

#### 8.6.1 适用面与接口版本

本节是 archive-v1 模式下评审原件的唯一存储契约；布局 §7.5 管根、Git 边界和切换授权。§8.1 至 §8.5 中 tracked 四件发布、同 inode Receipt、原 attempt 补写与跨 worktree 不保证的条款仅适用于 legacy-git，不能用于新归档发布。其候选资格、秘密扫描、Profile、轮号、额度、判词校验、权限与旧历史来源规则继续成立，以下逐项替换存储前提。§12/§14 原 tracked/inode 夹具继续作为 legacy 兼容验收，新模式增加 §8.6.7 的场景；历史裁定和旧失败不回写。

共享归档 helper 拟落本单元 review_evidence.py，由 review_channel.py 的 preflight/probe/review/respond 和各消费者调用。它负责引用语法、读取、校验、发布与恢复；不得由各消费者各自拼路径/补原件。历史 Git 的低层读取继续复用 repo-layout/history_read.py，不复制 Git 历史扫描器。新增显式命令由 review_channel.py 提供 `archive verify --ref <JSON-file>`、`archive restore --ref <JSON-file>`、`archive recover --attempt <id>`；verify 只读，restore/recover 为写操作须调用者已有适用授权，不能在 resume 或 preflight 暗中执行。新命令退出 0 = 指定操作完成、1 = 输入/来源/一致性拒绝、2 = 运行错误；成功仅限输出声明的范围，不授权发布、冻结或删除。

archive-v1 新请求采用 `request_schema = "review-channel-request/v5"`：除 `previous_round` 改为 `{evidence: EvidenceRef, response: ArchiveRef | null}` 外，v4 所有键/闭集及 r1 禁填、r2+ 必填规则保持。新 Receipt 采用 `receipt_schema = "review-channel-receipt/v3"`：字段集合承接 v2，新增 `evidence_storage: {kind: "archive", repository_id, round_key}`；verdict_path 与清单路径为从仓根计算的逻辑原路径，前缀必须为同一 round_key，不是 working tree 文件。`verdict_published=true` 仅在 §8.6.3 的已提交发布视图内有意义，不能仅凭一份磁盘 Receipt 判成功。清单文法、verdict/v4、effective-profile/v3、作者资格及数值闭集不变；Profile 内原路径值仍为同一逻辑原路径。旧 request/v4 仅用于旧运行模式及历史审计，不能静默按 v5 解释。继承读端显式支持既有 v2 和新 v3，不改写原件，也不因版本不支持而漏计历史轮。

**ArchiveRef** 为封闭 JSON 对象 `{kind: "archive", repository_id, object_sha256}`：repository_id 匹配 clone 绑定；object_sha256 是 64 位小写十六进制 SHA-256。不含绝对路径、可变 branch 或 URI。**EvidenceRef** 为二选一：ArchiveRef，或 `{kind: "legacy-git", commit, round_path}`。后者 commit 必须完整、可解析且为消费 view_commit 祖先，round_path 是原轮目录，仍按 §8.5 从同一来源取完整轮。禁止额外键、布尔冒整数、空值、绝对路径、`..`、反斜杠、NUL 和符号链接逃逸；路径按原 UTF-8 区分大小写。不得在一个引用中混合两种来源。旧记录自身已经固定的 commit/path 继续逐字解析，不能把新 ArchiveRef 默认为它的替代版本。

#### 8.6.2 物理形态与身份

归档根和备份根各有 repository.json（封闭键 schema = review-archive-repository/v1、repository_id）；不得仅凭目录名确认仓身份。相同根共享跨 worktree 的轮命名空间：subject 轴 round_key = reviews/<subject>/r<N>；task 轴 round_key = tasks/<task_record>/reviews/<stage>-r<N>，保持原 stage/轮次空间。尚未发布的 probe/失败 attempt 不占轮额，成功发布的有效判词占额，FAIL 判词也占额。

每根的 objects/<object_sha256>/ 存放 archive.json 及 payload/ 下原件。archive.json 使用 UTF-8、无 BOM、JSON key 按 Unicode 码点排序、紧凑分隔符、ensure_ascii=false、尾部一个 LF；对象摘要只对 archive.json 这些确切字节计算，避免自指。它的封闭键为 schema = review-archive/v1、repository_id、kind（round | attempt | response | legacy-import | inventory）、round_key、attempt_id（无旧值时 null）、parents（EvidenceRef 数组，缺省空）、files、legacy_source（null 或完整 commit + 原 round_path）、limitations（缺件说明数组）。files 每项恰为 path、bytes、sha256、role；按 path 的 UTF-8 字节排序、不得重复；bytes 是非负整数且拒绝布尔；role 闭集 taskbook | verdict | bundle-manifest | receipt | request | profile | candidate | reference | baseline | raw-output | decisions | other-original。path 是 payload 下相对路径，保留原文件名/相对目录；每项摘要校验实际文件字节，禁止符号链接及未列文件。限制作原始缺口说明，不能通过填写 limitations 放宽新 round 的完整性。

新 kind=round 包含本轮完整任务书、判词、清单、Receipt、实际 request、Profile、每件实际投递的 candidate/reference/baseline 字节、原始最终应答和归因所需调用输出；使用原清单身份将输入角色映射至归档 payload，不能拿当前文件替代被审快照。未发布 attempt 也保存已存在原件及实际阶段；真正不可路由/归档不可写时按原启动失败报告，不能伪造 Receipt 已耐久保存。预检在 provider 前验证根身份、可写性、备份可达及上一轮依赖；provider 后备份失效保留 pending，不重调 provider。

respond 不修改已发布 round：以 kind=response 发布原决定输入、通道生成 decisions.json、对应原 verdict/Receipt 身份，parents 按下文处置链规则绑定该原轮。重复相同字节返回同一引用；不同 Owner 输入产生新 response，并明确引用被取代的 response，旧对象保留。下一轮 request 的 previous_round.evidence 引用上一 round；前轮 FAIL 时 response 必填并指唯一合法处置链末项，前轮非 FAIL 时取 null。后继 response 的 parents 先列原 round、再列明确 supersede 的前 response，首次只有原 round；链分叉或引用不在该链上拒绝，不按目录时间选择。respond 的决定输入 schema 在归档模式采用 review-channel-decisions-input/v2，必填 schema 键取该版本，其他键集承接旧决定输入并新增 source: EvidenceRef 与 supersedes: ArchiveRef | null；旧纯 decisions.json 继续只读，新输出 review-channel-decisions/v1 的原判词身份和 Owner 文本语义不变，外层 response 对象承载新定位。首次 supersedes=null，后继必须指处置链末项。相同 Owner 输入的重复调用先返回既有 response，不因重新填写 decided_at 产生重复对象。同一 round 的 response 连续性由轮锁保护，已封存给下一轮的 response 不能被后继静默替换。kind=inventory 的 round_key 与 attempt_id 均为 null，parents 列全部已导入原轮引用，files 只承载精确 inventory 原件；它不占轮次，publication 落 publications/inventory/<object_sha256>.json，其余身份与双副本规则相同。inventory 文件逐件列原路径、source_commit/blob（本地原件为 null）、bytes/sha256、对应归档引用与 payload 路径，并分别列缺件和未分类保留项，校验时核实际集合，不能把未列源当可删。kind=legacy-import 允许原缺件/多成员形态，原字节完整保留但不自动变成可继承 round。准备快照经逐件验证才能导入，不能仅重命名 preparations 冒充协议对象。

#### 8.6.3 发布、双副本与崩溃恢复

归档以共同 primaryRoot 为写协调源。每个 round_key 在 locks/<sha256(round_key UTF-8)>.lock 取一次进程级 flock，至该进程结束保持；锁文件 inode 不替换、不删除，不依靠时间戳判断存活。分配 attempt、provider 调用、补发、归档发布、响应和最终轮号核验均在同一锁内；跨 worktree 的同轴同轮必须竞争同一锁。目录/设备前提为本机 POSIX 文件系统，网络盘 flock 不在保证面且配置拒绝；跨主机同时写同一产品线不受本协议支持，迁移前停止原写者。人手篡改锁、原件或备份不在机械防篡改保证内，哈希一致性不是第三方签名。

先在 primaryRoot/pending/<attempt_id>/ 分配状态与实际 request，沿已有 routed/sealed/calling/called/validated 阶段原子写入状态并 fsync，保留进程及 generation 身份、补发调用组和原失败分类。完成输出校验后构造完整对象，在 primary 的同文件系统内写临时目录、逐文件 fsync、校验、fsync 目录，再 rename 到 objects/<digest> 并同步父目录。目标存在则核原字节全同才幂等复用，否则拒绝，永不覆盖。

备份复制使用独立文件，不用硬链接。先写备份 pending，再逐件验证、fsync、rename 为同 digest 对象；随后构造 publication.json（schema = review-archive-publication/v1、repository_id、round_key、attempt_id、object_sha256、kind），按相同 canonical JSON 字节写入两根 publications/<round_key>/<kind>/<object_sha256>.json，备份先写、主根后写，均以临时文件+rename+父目录 fsync 落位。**只有两根相同 publication 字节与对象均验证通过才对调用者返回发布成功**，它是逻辑完成条件，不宣称两个文件系统原子事务。归档读端不以 objects 目录或 Receipt 单独存在判定已发布，必须校验双副本完成记录；纯审计可以报告主对象存在、备份不可用，但不能凭此继续继承、升 capability 或声称完成。

崩溃或断电留下的单边对象、完成记录或 pending 均保留；失败退出时报告实际持久阶段，沿现有 interrupted/失败分类，不产成功引用、不删除源、不新增第二次 provider 调用。显式 recover 在原持锁进程确已结束、generation 匹配后，从保存状态和已校验输出补完复制/完成记录；不确定外部调用是否完成时停报，不能自动重调。备份先出现的完成记录不授权主根自动恢复；恢复命令须显式选择同一 attempt。即使调用者未收到成功，后继扫描遇到同身份双副本完成轮仍占额且禁止覆盖；幂等返回原引用。并发防线之外不自动清理无效对象。restore 只从通过校验的备份恢复至指定空隔离目录；恢复根切换和源删除另依布局授权。

#### 8.6.4 读取、连续性和失败

scan_rounds、check_round_sequence、round_budget、load_previous、recover_baseline、respond、Registry、核差与历史查询使用同一解析器。扫描将当前 legacy、固定 Git 历史与有效 publications 按原轴/round_key 合并；相同身份去重，同键不同身份拒绝。kind=response/attempt/inventory 不计作已发布评审轮；legacy-import 依据原 Receipt 的已发布事实计数，旧缺 Receipt 不伪造已发布。旧 Git 与其 legacy-import 的等价身份取 legacy_source 的固定 commit/原轮路径及逐件原 blob/内容身份，不直接比较归档外层 digest；不能因包装摘要不同重复计数。顺序与额度不能因目录为空、模式切换或 clone 缺归档而归零。Git 内切换决定锚定 legacy 截止来源与初始化 inventory 摘要；本机缺归档/缺连续性证明时拒绝新轮，不创建空库继续 r1。publication 清单是派生读取结果，不是第二份 Workflow 状态。

新上一轮继承核对整轮 manifest/Receipt/判词/任务书与候选/reference/baseline 快照，Profile 仍按原规则继承；新当前候选恒从工作树取，不从归档回填候选。旧 Git 轮沿 §8.5 精确 hash 规则恢复基线，缺口保留。历史引用歧义拒绝，不自动挑最新原件。所有实际读入投递的字节仍过秘密扫描、大小限制和封存；来源表增加 EvidenceRef 与原路径，旧固定来源 commit/blob 列不伪填。读取只读，不联网、不修复、不调用 provider。

失败区分 archive-unconfigured、archive-unavailable、archive-identity-mismatch、archive-integrity-failed、archive-conflict、archive-incomplete；通道纳入 failure_code 闭集：调用前拒绝沿 preflight_failed/退出 1；调用后归档发布失败沿既有 reviewer_output_invalid/退出 1 并保留已观察调用事实，不能把存储失败描述成评审业务 FAIL；运行异常或 Receipt 无法写入退出 2。恢复期间仍按原 interrupted 的保守三维规则，不补造成功。respond 仍返回 decisions-invalid 并附来源原因；独立 verify 按 §8.6.1 返回。外部存储写失败可能连失败 Receipt 都不能耐久写入，此时 stderr 明示无法留存，不把 Receipt 总量性当已完成的保证。

#### 8.6.5 Git 内最小正式结果

最小结果放在已有正式决定承载件中：变更集为其 Changelog §7、Task 为对应 ruling，capability 更新为该次正式 Owner 决定；不另建逐轮 summary/report 文件，不复制完整 finding 叙述、任务书、清单或调用日志。使用一个标记为 review-result 的 JSON 代码块，封闭键 schema = review-result/v1、source（EvidenceRef）、input_manifest_sha256、candidates（path/bytes/sha256 数组）、outcome（PASS | FAIL | NO_VALID_VERDICT）、residuals（id/disposition/decision_ref 数组）。id 只列影响当前正式决定的保留项，disposition 为已核的 fix | skip | approve；没有则空。candidate 身份须按清单逐件核验；probe 无候选且清单身份可为 null，不得伪造 PASS。新工具输出块由实际原件生成并校验，Human 核差确认后纳入正式决定；旧文本来源不能自动转为此新格式。块不是审批，也不改变 Owner 授权边界。

check.ref 或 handoff 可引用 `<正式件路径>#review-result`；一个文件恰一块，后继结果以该文件自身的合法事件/追加纪律承载，旧不可变 ruling/卷不改。多 subject 共用变更集同一块，不在每个定稿卷复制整份候选列表；Owner 定稿卷的一段指针形制保持。变更集进行中逐轮处置正文均在归档，Git 中仅记录阶段已到何处、待 Owner 的具体决定及其引用；不得把完整报告换名放入进度、Changelog、diagnostics、附件或压缩包。

#### 8.6.6 Registry capability 凭据

Registry `registry_schema = "review-channel-registry/v4"` 将 PROBED/REVIEW_ENABLED 的 receipt_ref/receipt_commit/receipt_sha256 改为单一 evidence 对象，二选一：`{kind: "legacy-git", receipt_ref, receipt_commit, receipt_sha256}`，或 `{kind: "archive", ref: ArchiveRef, receipt_path, receipt_sha256, decision: {commit, path, locator}}`。其余模型/状态/绑定字段不变。CONFIGURED/UNVERIFIED 不要求凭据；已声称更高状态缺凭据拒绝整个 Registry。v3 保持兼容只读其旧字段，迁移工具须保留实际元组和旧事实，不由通道自写 Registry。

legacy-git 凭据核验固定祖先 commit 的原 Receipt blob 及摘要；工作树同路径在场另作逐字节比较，不在场允许固定来源读取。diagnostics probe 和原 r31 等同按旧三维与结局核验，不再要求原件继续占 HEAD。archive 凭据要求双副本可验证、Receipt v3 的来源与实际 mode/phase/classification/三维/发布身份符合 §6.6；PROBED 的 probe 或 INVALID review 只承载 attempt，REVIEW_ENABLED 必须是有效 published round。decision 的 commit 为消费 HEAD 祖先，path/locator 固定 Git 中的 review-result 块，块的 source 与 ref、candidate 身份及结局逐项相符。更改本机原件及活体 Registry 哈希不能改变固定 Git 决定块；Human 伪造全部原件并正式提交仍属于人为越权，不宣称 cryptographic attestation。

旧 §6.6 中将 probe/INVALID Receipt 晋升到 records/diagnostics/review-channel/<日期>/ 的 Git 路径退役；新失败/探针完整原件直接归档。此改变不降低 capability 证明标准，不因归档成功自动提升 Profile 状态，不因历史可读声称 provider 此刻可用。

#### 8.6.7 施工验收与启用

冻结与当前起草都不启用本节。按布局 §7.5 验收后以正式切换决定绑定版本、产品线、legacy 截止来源及归档 inventory 身份；首次执行本集评审仍遵守当前冻结协议，不自行采用新字段。验收原件保存于仓外，Git 只留正式结果。

- 一条 subject 轴和一条 task 轴完成 r1 FAIL、respond、r2 PASS；核真实输入快照、处置与 Profile 继承、额度和正式结果；新 clone 缺根拒绝继续，从备份恢复后按原身份继续。
- 两个 worktree 同轴同轮同时发起，恰一个获得调用/发布权；不同轴可并行；初始化清单缺失、轮号冲突、旧 schema 不支持继承均不能少计轮次。
- 在阶段写入、主对象 rename、备份复制/rename、各完成记录落位和返回之间注入失败；保留原源和 pending，无成功误报、不重复 provider、恢复幂等。
- 全量备份恢复、缺一个候选/reference/baseline、摘要被改、同名不同来源、符号链接、根别名、备份硬链接、两根同盘事实均有正负例；秘密扫描及调用组保守聚合不变。
- v2/旧 Git、r31 Registry、probe/INVALID diagnostics、gov-t11 非标准历史轮及 CL-41 缺口各按原事实读取；缺原件明确拒绝原件依赖操作，最小正式结果离线可读。
- 完成一条新评审到受治理 publish 预检的完整链；检查每个新增 commit 的 tree/blob，包括先加后删、改名、已知原件 bytes 换路径；检查不能解析则拒绝。未得到 push 授权只运行只读预检，不制造真实远端写入。

## 9. 与既有冻结决定的关系

| 既有决定 | 关系 |
|---|---|
| `spec.md@r6 FR-21` | task 轮五题闭集逐字承接其五维度（Fidelity / Goal Soundness / Boundary / Acceptability / Executability，§6.4；Amendment 4） |
| `spec.md@r6 FR-40` / `FR-41` | 本设计的直接承载：§5.3 唯一入口、§6.8 资格 fail-closed、§6.5 机读校验与拒收、§6.4 契约注入；§6.6 Receipt 三要素、§6.11 capability 凭 Receipt 演进、`formal_review_authorized_by_owner` 随 Receipt 记录 |
| `FR-37` / `FR-50` | 清单耐久保存（legacy-git 原件或 §8.6 仓外归档）、Receipt 记清单哈希；本设计不改证据留存面（§2.2、§8.3） |
| `FR-38` | 判词 `previous_findings_disposition` 与 `location` 为其判词侧承载；看守归 gov-t11 |
| `FR-28` | Receipt `round_budget` 为 Policy Gate 事实面；评估归 feature-t6 |
| `task.template.md` / `ruling.template.md`（`mechanisms/artifact-templates/`；原 task-artifact-schema §7.2 / §10，该正本已随减重第 5 步退役） | review-skip 衔接（§6.9）；四件最低成员与落点（§8.1，自承载）；不新增 tracked member；stage 闭集自承载（§6.1） |
| delivery-method §8 | 跨模型提供方按模型提供方判定（§6.8）；Receipt 含产出方与评审方各自工具、模型、提供方身份及判定结果（§6.6）；异源评审 optional、default-on、Human 当次可开关（§6.9 评审关闭） |
| 布局权威 §5.1 / §7 | 新单元按文法成家无需 amendment（§5.1）；证据落点两轴分流照录（§8.1） |
| 退出码与净化启动的历史来源 | 原结论正本已退役；现行消费者由本设计 §5.3 独立承载，数值与启动行为不改 |
| handoff-protocol §4.2 | `verdict` 锚读判词机读块 `verdict` 字段，发布的判词恒满足严格文法（§6.5.3） |
| `D-09@r1` | 同轮并发防线（§8.2） |
| freeze-record 设计 §5.3 / §8.1 | `review_anchor.reviewed` 消费清单 role 为 candidate 的全部项，C1 相等断言对多候选束逐件成立；判词 `candidate` 字段保留为首候选身份，使其 §8.1 读取约定「判词自述的 `candidate.sha256` 属候选输入集合」原样成立；`review_subject` 按其 §8.1「未必与成员 subject 同名」可取变更集轴（Amendment 2） |
| delivery-method §7.6 | 「在通道支持多候选之前…各受锁成员逐件为候选」的限制按其末句「多候选评审出生后本限制随之解除」自行解除：一个变更集全部字节变化的受锁成员可同束为候选、一轮一次投递、一份判词（§6.2 第 1 条、§14 S20）；同一 subject 多个受锁成员同时变化的修正自此亦可组成变更集；其文本对齐属该设计自身的对齐级 amendment（Amendment 2） |
| 创始档案库通道契约 r5 与 runner 设计 r5 | 继承基线（gov-t8:OD-02 其十一）：借形与借语义，不借权威；逐项对照见 §10.4 |
| freeze-record 设计 §4.3 | 域一引用的现行修订号标注按其两条解析规则取值（§6.2 第 2 条，Amendment 4）；通道不校验记录体、不判失败码 |
| `AGENTS.md` §3 工具借用例外 | 本设计冻结并经 §14 S1 实证后退役（§11） |

## 10. 设计输入处置表

### 10.1 gov-t8:OD-02 十七条

| 条 | 裁定 | 处置 | 落点 |
|---|---|---|---|
| 其一 | 证据留存取甲案 | 吸收 | §8.3、§6.6 Receipt 不内嵌清单、§6.3 任务书生成 |
| 其二 | Python 3.12 标准库；模块化包，适配器住 `adapters/` | 吸收。r1 至 r28 候选曾以「布局门只许两槽位」为由改为扁平，该依据对布局权威不实（末槽开放）、只对现行门实现属实；Owner 2026-09-02 裁定恢复 `adapters/`，门缺口登记 KB-02 为施工前置 | §5 |
| 其三 | 七条提升点全做；能力与契约哈希解耦 | 吸收 | §6.11、§7、§6.10、§6.3、§12 |
| 其四 | 轮次额度语义 | 吸收 | §6.10 |
| 其五 | 可插拔面一字不弱化 | 吸收 | §6.9 |
| 其六 | 异源 = 模型提供方 | 吸收 | §6.8 |
| 其七 | 判词结构化字段 | 吸收 | §6.5.1 |
| 其八 | 信封包容三级 | 吸收；「机读块放前」采纳为注入要求 | §6.5.3、§6.5.4、§6.4 |
| 其九 | Anthropic 路径探针后定 | 吸收；本设计只冻结要求 | §7.3、§7.4、§16 |
| 其十 | 档案库台账八类问题 | 吸收 | §10.3 |
| 其十一 | 档案库能力定义逐项继承 | 吸收；逐项对照表随 Amendment 4 退役（原 §10.4，Git 历史） | §10.4（已退役） |
| 其十二 | 术语不用隐喻 | 吸收 | §3 |
| 其十三 | 直接接口路径含官方与聚合商 | 吸收 | §7.4、§6.11 |
| 其十四 | 工具版本只记录不提醒 | 吸收；较档案库 r5 再去掉 preflight 差异报告 | §7.6、§6.11 |
| 其十五 | `system_default` 改为 Registry 数据字段；standing selection 文件退役 | 吸收 | §6.11、§6.9、§13 F |
| 其十六 | 模型提供方标识改为受锁设计正本内的封闭集合，大小写敏感精确比较（gov-t5 对齐） | 吸收 | §6.11 `vendors` 表、§6.8、§6.1 |
| 其十七 | 补发重建模：补发是 review attempt 内部的第二次调用而非独立 attempt——同一目录、同一锁、同一 Receipt（记提取等级、补发消息哈希、不变性核对结果）；不新增子命令、mode 值、分类值、状态表行或能力证据路径；独立 `reemit` 子命令退役，补发失败即本 attempt INVALID、按规则 7 归因后重投 | 吸收 | §5.3、§6.1、§6.5.4、§6.6、§6.7、§6.11、§8.1、§8.2、§12 第 8 / 9 类、§14 S4 |

### 10.2 legacy 台账行

- `legacy:OD-15`（缺口一次报尽）：r1 至 r4 的承载 = §6.5.1 的 `exhaustive` 与 `origin` 两字段加 §6.4 穷尽性注入。Amendment 4 起 `exhaustive` 字段与穷尽性注入退役（成因统计已由 v3 判词的机械计数达成，减重第三批诊断记录，台账 `repo:OD-10`；穷尽核对是整改自伤与未改动区阻断两类成因的来源之一），`origin` 保留并升为阻断资格判据（§6.5.2 第 14 条）；该台账行随本修订闭合。
- `legacy:OD-17`（证据留存）：甲案，§8.3；乙 / 丙路线转 gov-t9，本设计 §2.2 显式排除。

### 10.3 创始档案库台账八类问题

| 类 | 问题 | 处置 | 落点 |
|---|---|---|---|
| 1 | 任务书与被审输入的事实字段靠人手写 | 结构性消除 | §6.2 引用解析与封存、§6.3 生成、§6.4 注入 |
| 2 | 多轮 FAIL 链无上限、无推进规则 | 结构性处置 | §6.10；`human` severity 使停报判据机械化 |
| 3 | 能力绑工具版本、Registry 入锁面、契约哈希作废快照 | 结构性消除 | §6.11、§7.6 |
| 4 | 机读块提取绕过四代 | 结构性处置 | §6.5.3 三级包容 + 严格发布文法 + §7.4 结构化输出 |
| 5 | 派单形态不统一、并发重派、Claude 登录态不可达 | 结构性处置 | §7 适配层、§8.2 文件锁、§7.3 探针要求 |
| 6 | 落点与登记逐案裁定、体积失控 | 结构性处置 | §8.1 派生、§8.3 去重（§8.4 自动登记已随 Amendment 4 退役） |
| 7 | 评审面被活文档、状态头自述、已接受残留污染 | 结构性处置 | §6.3 已接受残留段与 `accepted_residuals_acknowledged`；被审对象状态头由通道在任务书状态头覆盖式声明 |
| 8 | 评审方漏检、运行时不遵守配置不被观察 | 部分处置，余为残留 | §6.4 五题闭集、§6.5.1 `location`；模型漏检与 KB-37 残留见 §15 |

### 10.4 创始档案库能力定义的逐项继承对照（已退役，Amendment 4）

本节原以 C01 至 C65（通道契约 r5）与 D01 至 D60（runner 设计 r5）逐条登记创始档案库能力定义的继承与变更裁定（gov-t8:OD-02 其十一）。该对照只服务本仓创始期的接管核对，自 Amendment 4 起退役（Owner 2026-09-06 裁定 F10 甲），正文见 Git 历史（FROZEN r4）；本设计各节的规范条款不因此改变，其十一的裁定事实由 §10.1 承载，序号不复用。

## 11. 借用形态退役与迁移

1. 本设计冻结并经 §14 S1 一次真实异源评审实证后，`tasks/README.md`「gov-t8 出生前的临时构束补充」一节整段退役：其中「输入取绝对路径、角色标注、reference 要选到够、清单由脚本算、request 落 attempts、只取本仓文件」六条已由 §6.2 机制化；「subject 与轮次编号」表由 §6.1 的 `stage` 字段消解；「送审前先 preflight、封存后不改、四个子命令、轮次号唯一出处、三件闭合锚、先固定基线、改生成器不只改生成物」七条全部由 §6.2 / §5.3 机制化。退役方式 = 删除该节并在其位置留一行指针指向本设计（`tasks/README.md` 页首「后继接管对应面时本文件须同步收窄或退役」的既定程序）。
2. `AGENTS.md` §3「可借用档案库工具」例外条退役的输入随交付批呈 Owner（契约修改按其自身程序）。
3. 档案库通道产生的历史判词、Receipt、Registry 能力状态不迁移、不倒写、不作为本仓通道的 capability 证据；本仓通道各 Profile 的能力从 `CONFIGURED` 起，凭本仓通道自己的受治理 Receipt 晋升。

## 12. 交付物清单与自测承诺

**施工批交付物**：§5.1 全部可执行物与 Registry 数据文件；`fixtures/`；`tasks/README.md` 收窄；本设计 §7.3 形态填入（若探针采用）。

**自测承诺**（离线、零网络、零费用；等价类逐条有能红能绿的双向证明；按 KB-36 不接线，人工发起）：

1. Request 校验全封闭（顶层非对象、类型错、布尔冒充整数、字符串冒充授权布尔、round 文法、stage 闭集、profile 半对；`request_schema` 非 v4、`review_brief.questions` 或 `standard_questions` 在场、`evidence_limits[].kind` 取二值闭集外的值各一负例，Amendment 4）。
2. Registry：schema 版本、defaults 必填与类型、kind 与 runtime 组合合法性、key / base / auth_source 双向约束、capability 元组必填、receipt_ref 内容驱动核验、`max_input_bytes` 必填面。
3. 秘密来源：zshrc 三种字面量正例、substitution / glob / 重定向 / 管道 / 重复 / 缺失负例、不泄值；认证文件三态；扫描集扩展；落盘前终检命中即不发布。
4. 被审输入：引用解析命中与缺件、豁免声明放行、禁名自动改名、封存后来源改动不影响投递、上一轮闭合锚自动入、基线从 Git 历史取、`baseline-unrecoverable`、容量守卫；**多候选**（Amendment 2）：多件候选逐件解析、候选互引记「候选之一」、逐候选基线与固定投递名、候选来源路径集合与上一轮不等 → `inherit-unanchored`；**任务轴多候选**请求文法失败（R33-B1）；**r1 改动区基线**（Amendment 4）：现行冻结事实身份自 `freeze-records.jsonl` 行与 `.md` 记录各取一例并恢复字节、首冻候选声明整件为改动区且不判失败码、身份在案而字节不可恢复 → `baseline-unrecoverable`、r1 不加入 `previous--` 族。锁值引用件的正负例随其形态于 Amendment 4 退役。
5. 任务书渲染：同输入两次渲染逐字节相同；十节齐备；差异统计正确（多候选下逐候选一小节；r1 含改动区节与基线 SHA-256，Amendment 4）；对象与目标逐候选一行、首行为首候选；问题集节恰为该 stage 五题（task / impl 各一例）；r2+ 含上一轮决定摘要；上一轮 finding 全列；封存后改动来源文件不改变任务书、清单与投递字节（R4-B4）；封存中来源变化 → `seal-mismatch`。
6. 指令注入：契约文本含全部字段名与闭集、该 stage 五题闭集（task / impl 两套各一例：题号集合恰为五题、`question_assessments` 字段行无 `exhaustive` 成员）、机读块在前要求、差异块之外取 `unchanged_region` 且不得阻断句（Amendment 4）；**骨架行判据**两向与**往返性质**（Amendment 2：占位骨架逐行在场；任一有效机读块以实际值渲染的叙述经第 13 条恢复后逐项相等）；probe 模式与信封类、校验类补发调用的指令形态各异。
7. 判词校验十四条规则各有负例与正例；题号集合缺题、多题、重复、取另一 stage 套各一负例（Amendment 4）；**规则 14**：`origin = unchanged_region` 且 `severity = blocking` → INVALID、`verdict_problems[]` 含 `rule-14:<id>`、不补发、无 tracked Receipt；同 origin 取 `non_blocking` / `human` 放行；三类 finding 编号连续；`previous_findings_disposition` 等集；`accepted_residuals_acknowledged` 等集；`candidate` 绑定；`candidates` 与清单候选逐项同序相等（子集、超集、重复、首项互换、三候选时保持首项而交换后续项各一负例，R32-B2）；`scope_files_read` / `location.file` 取未投递的仓内路径拒绝；两类可确定性整改项的分类各有正负例（Amendment 2）。
8. 信封包容：一级严格正例；二级六种 repair 各一正例且 JSON 值区段字节不变断言、发布文档满足严格文法断言；三级触发条件（截断、多块）；补发交叉核对通过与不通过各例；补发不消耗额度；**校验类补发**（Amendment 2）：已知值缺陷与叙述缺陷各一正例（补发后 VALID、`reemit_trigger = validation`、`reemit_reasons` 非空、`reemit_unverifiable_fields` 为空数组、`tier = reemitted`）；补发块改动判断字段的负例（`reemit-invariance-mismatch`，`mismatched_fields` 列该字段）；含判断字段缺陷的失败不触发补发（INVALID、无第二次调用、`reemit_trigger` 为 null）；补发后仍有失败项 → `verdict-invalid` 且 `reemit_trigger` 在场；补发至多一次（补发结果再次落入触发类不再调用，`calls[]` 恒至多两项）；`--no-reemit` 下两类均 `reemit-disabled`；**补发与文件锁**：补发调用在同一 attempt、同一进程、同一持有下完成，取锁调用在进程内恰执行一次（静态断言）；补发期间另一外部 attempt 得 `round-in-progress`；补发调用失败 → 恰一份 Receipt、tracked 目录无任何成员；**补发调用失败分类与核对结果**（R22-B1、R22-B3）：补发调用四类基础设施失败各一例 → 按 §6.7 同名行分类、失败码记 `call_index = 2`、`invariance_check.status = not_reached`；补发返回不可解析 → `reviewer_output_invalid` + `reemit-unparseable`；不变性不符 → `reviewer_output_invalid` + `reemit-invariance-mismatch` 且 `mismatched_fields` 与 `verdict_problems[]` 逐字段一致；通过 → `passed`；未补发 → `invariance_check` 为 null。
9. 分类闭集与三维表：三维四行组合穷举（probe / review）；经补发后校验 VALID 的 review attempt 分类 `completed_with_valid_verdict` 且 `extraction.tier = reemitted`、`reemit_raw_message_sha256` 在场、`reemit_trigger` 取两值之一（Amendment 2）；**两次调用保守聚合**（R22-B2）：首次 `SUFFICIENT` 补发 `MISMATCH` → `MISMATCH`；首次 `INSUFFICIENT` 补发 `SUFFICIENT` → `INSUFFICIENT` 且不形成 `REVIEW_ENABLED` 建议；首次 `PROVEN` 补发 `NOT_PROVEN` → `NOT_PROVEN`；`calls[]` 恒两项、首项字节不被覆盖；三个归约字段：两项相等 → 取该值；任一不等 → 三字段 null 且 `profile_binding = MISMATCH`；仅 `runtime_version` 不等 → 归约字段照常取值、三维不降，运行时组按 §6.6 确定性表示（首次值 + `changed_within_attempt = true`）（R24-B1、R25-B1）；秘密命中维持保守分类。
10. 资格：同厂、unknown、空集合、human_only 两向、混合写者集合；vendor 闭集（其十六、R6-B3）：表外值（含大小写变体 `anthropic`）在 Registry 装载与评审请求校验两端各拒绝、表内值放行；Human 项三字段保留字正例、`tool = human` 配模型 vendor 负例、模型项配 `vendor = human` 负例、Human 与模型混合作者派生集合只含模型 vendor 正例、human_only = true 配模型项负例。
11. 选择与继承：三级优先级、本级失败不下探、显式改选记录差异、治理链锚定、前驱关系、Registry 漂移防线、**契约哈希不参与继承**（设计哈希变化后旧快照仍可继承的正例）、review-skip 轮跳过与 `round-gap-unexplained`。
12. 轮次额度：默认 2 取自 Registry（Amendment 4）；同轴两轮各带 tracked Receipt 后第三轮 preflight → `round_budget_exhausted` 且 stderr 含允许轮数 2；Request 覆盖；加轮累加；到额拒绝且提示含末轮阻断项数；再次加轮放行；跳过轮不计；补发不计；判词 INVALID 的 attempt 不计。
13. 运行时版本：不同版本不拒绝、不降级、Receipt 只记录；`changed_across_rounds` 四情形各一例（无上一轮 → null；显式跨适配器改选 → true；同适配器版本不等 → true；同适配器相等 → false，继承与显式同适配器改选各一例取值相同）；两次调用版本不同 → `runtime.tool_version` 取首次值、`changed_within_attempt = true`、`calls[]` 两项各留原值、归约字段与三维不变、无任何提示（R25-B1）；单次调用 `changed_within_attempt = false`；能力元组不含版本。
14. 适配器接口：假适配器注入下契约层端到端；codex 适配器的配置生成、环境构造、受保护前缀；http 适配器三协议的请求体构造、内联定界、结构化输出请求、应答模型标识提取、聚合商 `logical_model_match` 判定；claude 适配器按探针结果补入。
15. 提交协议状态机（R3-B2 至 R12-B2）：跨 worktree 声明断言（威胁模型其二在文本与自测均限定同一工作树）、原子入位、目标不存在正例、目标存在（空 / 非空 / 四件齐备 / 含任何标记或未知内容）一律拒绝且不改动（`tracked-round-dir-occupied`）并产失败 Receipt 与暂存清理、并发两进程只一个 rename 成功且失败方清理暂存并产失败 Receipt、rename 失败 → 暂存删除 + 失败 Receipt + tracked 未触碰、rename 后回链失败 → 只报告且 tracked 四件齐备、attempt 内过期暂存目录 → 前置整体删除、rename 之前 `publish.tmp-*` 内容不被任何读端当作 Receipt、每条路径恰一份可观察 Receipt（总量性）、tracked 目录任何时刻只有两态（对每条失败路径断言）、协议中不存在 mkdir 目标路径、写入或删除预先存在目录、以及 rename 之后写入 tracked 目录的调用（静态断言）、次序、文件锁两向。
16. 决定文件与 `respond`（Amendment 4；原「证据登记衔接」随 `register` 退役）：五条校验规则各一负例（`decisions-invalid`）；往返正例 = r1 判词含 blocking / non_blocking / human 各一条 finding → `respond` 写入 `fix`（带 instructions）/ `skip`（blocking 带 work_item）/ `approve` → 决定文件原子在场、stdout 报告对象 `next_round` 成员含处置段与派生残留项 → r2 请求件按其填写后 preflight 通过、任务书含决定摘要、Receipt `decisions_sha256` 在场；缺决定文件 → `decisions-missing`；`remediation_statement` 不以处置段起始、`accepted_residuals` 缺派生项或 text 不等、`verdict_sha256` 与上一轮判词不等 → 各判 `decisions-mismatch`；blocking 的 `skip` 缺 `work_item`、`owner_verbatim` 为空、finding id 集合缺一 → 各判 `decisions-invalid`；`respond` 对输入内在场的 `verdict_sha256` 拒绝；同轮 Receipt 缺席或其 `verdict_sha256` 不等于判词字节 → `respond` 拒绝；再次 `respond` 后以旧输出起草的 r2 请求件 → `decisions-mismatch`。
17. 变异验收：`fixtures/mutations.json` 列出「删除或反转某条规则」的变异清单，引擎逐条施加后对应负例必须红，全部通过才算自测绿（gov-t8:OD-02 其三 selftest 项）。
18. 引用解析三分（R1-B8、R3-B4）：仓根闭集从 rules_catalog.json 取得（缺键即 `root-closure-unavailable`）；对闭集每个根族各一组不存在 / 歧义 / 未投递负例；计划交付文件不判缺件；仓外豁免放行、仓内正本豁免拒绝；**现行修订号标注**（Amendment 4）：域一引用修订号等于、不等于现行修订号各一例均放行且任务书并列标注；现行修订号自 `freeze-records.jsonl` 末行（`retire` 行不计）与编号最大的 `.md` 文件名各取一例；引用路径在任何 subject 冻结事实内零命中 → 标注「现行修订号不可得」、不判失败码；引用一个不在案的修订号 → 放行（核对已退役，负例改为断言标注在场）。锁值引用件、档案库时代修订指称与在案记录可信边界的全部正负例随其形态于 Amendment 4 退役。
19. 最小可路由解析与阶段 Receipt（R1-B7、R3-B5、R3-B6、R4-B3、R12-B1）：四路由字段任一缺失或不合文法 → `request-unrouteable` 零目录；在 `records/runtime-environment.jsonl` 外的解释器身份下 preflight 不再退出码 2（Amendment 4，V10）；路由通过后在 `routed` / `sealed` / `called` 各阶段制造失败 → 各恰一份 Receipt 且字段必填 / null 规则逐项断言；调用前内部异常一例；probe 与 review 的调用后内部异常各一例，三维取值逐项断言且 probe 例不产生能力建议高于 `UNVERIFIED`；**崩溃总量性**（R13-B1、R13-B2、R14-B1 至 B3、R15-B2、R16-B2）：分配 rename 前（`.alloc-*` 所有者已死 → 删除、无 Receipt、无 attempt；所有者存活 → 不动）、`routed` / `sealed` / `calling` / `called` / `validated` 五态各一例（分别在该态记录写出后、下一态记录写出前模拟进程终止）、补发调用的 `calling`（`call_index = 2`）与 `called` 两切点各一例（补产 `calls[]` 分别恰一项 / 恰两项，三维按 §6.6 聚合规则逐项断言）与发布 rename 后回链前一例：下一次 preflight 分别补产 `interrupted` Receipt 或回链，且不重复补产；每例断言 = Receipt 字段恰为 §6.6 补产行按该态列出的闭集（在场字段逐项等于 `attempt.json` 记录值、其余字段逐项为 null、事实只来自 `attempt.json`），三维逐态断言（`routed` / `sealed` = `NOT_PROVEN` / `INSUFFICIENT` / `NOT_REACHED`；首次 `calling` = `INDETERMINATE` / `INSUFFICIENT` / `NOT_REACHED`；补发 `calling` = 首项与 `INDETERMINATE` / `INSUFFICIENT` 的聚合 / `NOT_REACHED`；`called` = `calls[]` 聚合值 × 2 / `NOT_REACHED`；`validated` = 记录内实际值 × 3，一例取 `INVALID`），`effective_profile` 分组断言（`sealed` / 首次 `calling` 例：选定组在场、调用组与发布组 null；补发 `calling` 例：选定组 + `calls[]` 恰首项 + 运行时组、发布组 null；`called` / `validated` 例：选定组 + 调用组（`calls[]` 与三个归约字段）在场、发布组 null；`validated` 例另含 `extraction`）；pid 存活时不动；pid 被复用（同 pid 不同启动令牌）→ 视为不存活并补产；僵尸 → 视为不存活；令牌不可得 → 不补产并报告 `liveness-undeterminable`；恢复者写临时文件后 link 前崩溃 → 最终路径不存在、临时文件由下一次前置删除、再次恢复成功；恢复者 link 后清理暂存前崩溃 → Receipt 完整、暂存被删除；两个恢复者并发 → 恰一份 Receipt（失败者 `EEXIST` 退出并清理自己的临时文件；`synthesized_by` / `utc` 为恢复事实，不断言字节相同，记录派生部分逐字段相同）；**同轮文件锁**（R14-B2、R16-B1）：持有者存活 → 第二个 attempt 得 `round-in-progress` 并产 `preflight_failed` Receipt；持有者被 `SIGKILL` → 下一个 attempt 不经任何清理即取得锁；持有者 pid 被复用且新进程不持锁 → 取得锁；`.in-progress` 的 inode 跨全部用例恒定、通道任何路径都不 `unlink` / `rename` 该文件（目录快照断言不存在 `.in-progress.*` 一类文件）；诊断内容陈旧或为空不影响判定；活跃分配目录不被另一 preflight 删除。
20. 严格发布文法与分离（R1-B6、R2-B1、R3-B1）：候选块在开头 / 中间 / 末尾三正例发布文档形态相同且 JSON 值区段逐字节等于原消息中的区段；前缀含非空白字节 → 三级；JSON 字符串内含换行与反引号不误判闭栏；wrapper 的 `machine` span 提取正例与 `machine` 缺失 / 重复负例；收尾散文进入叙述正文并记 `trailing-content`；块不在开头记 `block-relocated`；候选块 0 与 ≥ 2 进入三级；补发不变性核对每个可恢复字段各一负例；`reemit_unverifiable_fields` 记录正例；校验类补发对每个判断字段各一逐字节不等负例（Amendment 2）。
21. capability 准入矩阵（R1-B3、R4-B2、R5-B2）：五状态 × probe / review 十格逐格；`CONFIGURED` 无绑定装载正例；声称 `PROBED` 缺绑定装载负例；成功 probe Receipt 与 INVALID-但-PROVEN+SUFFICIENT 的 review Receipt 各一份 exact copy 到 diagnostics 落点且受跟踪 → 作为 `receipt_ref` 装载正例（`PROBED` 两条路径可达）；同一 Receipt 仍在 attempt 目录（未受跟踪）或落点不合 → 拒绝；工作树文件与 `receipt_commit` 中 blob 不等 → 拒绝（同时改写文件与 Registry 哈希的负例）；`receipt_commit` 不是 HEAD 祖先 → 拒绝；blob 与 `receipt_sha256` 不等 → 拒绝；原件在场且不等 → 拒绝；`routed` / `sealed` 阶段 Receipt 作 `receipt_ref` 拒绝；`mode` 缺失或不在闭集 → 拒绝。
22. 适配器发现（R1-B11、R28-B1）：Registry 引用不存在的 runtime → `runtime-adapter-missing`；假适配器 `SUPPORTED_KINDS` / `SUPPORTED_TRANSPORTS` 驱动的组合校验两向；`adapters/<x>.py` 以文件路径装载、模块名 `review_channel_adapter_<x>`，`x = http` 时标准库 `http` 不被遮蔽一例；`adapters/*_selftest.py` 被自测引擎发现一例。
23. 直接接口单一输出模型（R1-B10）：对象形状正例渲染为严格文法；`narrative` 违反叙述约定负例；`tools_used` 非空负例。
24. canonical JSON（R1-N3）：等价对象不同序列化同哈希；非 ASCII 不转义；键序。

## 13. Rejected alternatives

### A. 适配器与其余模块一律扁平（不建 `adapters/`）

未采用（R28-B1 整改）。r1 至 r28 候选曾取此形态，依据「布局门只许 `hooks/` 与 `fixtures/`」——该依据对布局权威不实（§5.1 末槽开放、子目录合法、改用无需上游 amendment），只对当时门实现属实（历史 KB-02）；Owner 其二明定 `adapters/`，2026-09-02 裁定恢复。判定逻辑的其余模块仍取扁平前缀，属规模裁量（原 gates r13 设计 §4.1 同理，历史比较），不是上游约束。

### B. 沿用单文件 runner 直接迁入

否决。Owner 裁定其可读性与可维护性不达标（gov-t8:OD-02 其二）；与 Codex 深耦合的 argv、配置键、事件流解析散布全文，无法在不动契约层的前提下新增评审方运行时。

### C. 启发式修复 JSON 本体

否决。补引号、删逗号会改变语义而无人察觉；判词是承重证据，宁可花零头成本让同一评审方补发（§6.5.4）。

### D. 工具版本差异只报告不拦截（档案库 r5 形态）

否决。Owner 指出报告本身就是每次升级都出现的提醒（gov-t8:OD-02 其十四）；版本作为事实进 Receipt 已足够追溯。

### E. 评审证据分层缩面或移出本仓

前序决定（历史）：未采用（`legacy:OD-17` 复看取甲），当时转 gov-t9。CL-52 仅调整可达 Git 历史内的有条件 HEAD 退出，不采用外部存储替代永久原件，不缩减首次发布的四件最低成员；实际启用按 §8.5 与布局 §7。 本项关于新证据不得仓外耐久存储的旧取舍由 CL-55 §8.6 候选替换，旧 Git 历史仍保留。

### F. standing selection 文件

退役（Owner 2026-09-01 裁定，gov-t8:OD-02 其十五）。它是持久型显式选择的第二通道，与「每轮显式指定或继承」重叠，且住仓根、未跟踪、跨 worktree 不一致（D-09 下多 worktree 并行时尤其）；显式选择只经评审请求承载。

### G. 断路器到额即关闭通道

否决。Owner 裁定通道永不因额度关闭，加轮无限次（gov-t8:OD-02 其四）。

### H. Receipt 内嵌完整清单

否决。清单是独立最低成员，内嵌即每轮重复入库（`legacy:OD-17` 样本二实测）。

### I. 直接接口适配器实现工具循环

未采用。让评审方经函数调用逐件读文件会重造 coding agent 的工具循环（档案库契约 §1「不重新实现 Agent tool loop」），且使「一个 attempt 不等于一次请求」的残留延续到本路径。内联投递加容量守卫更简单，超限即拒。

### J. 契约哈希钉扎 Profile 快照

否决（§6.11）。它使每次 amendment 作废全部快照；快照可继承性由 `profile_schema` 版本号与治理链锚定承载已足。

### K. 常设问题集默认关闭

未采用（r1 至 r4）。三题对应三条复发问题（OD-64、KB-39b、KB-30）；默认开、Request 可显式关并记入 Receipt。Amendment 4 起常设问题集与其开关整体由五题闭集取代（§6.4），三题并入 impl 轮五题，本条只余沿革。

### L. 任务书全部由人手写

否决。事实字段手写是档案库台账复发最多的问题类；人写段只剩背景、核对面、限制声明与问题正文。

### M. 叙述缺陷由通道自机读块渲染叙述、不再调用评审方（Amendment 2）

否决。零调用即零成本，但发布的叙述将全部为通道生成、评审方原叙述内的推理文字（finding 小节正文）全部丢失，判词的人读价值退化为 `summary` 字段；且「最终消息即判词」将不再成立。校验类补发保留评审方为叙述作者，通道只给结构行。

### N. 校验类补发扩至判断字段缺陷（Amendment 2）

否决。缺 `question_assessments`、finding id 文法错、PASS 带 blocking 一类缺陷的修复都要求评审方改写判断，通道给出「正确值」即替评审方改判断（§15 原则）；这类失败按规则 7 由 caller 归因后新 attempt。

### O. 补发链式多次（Amendment 2）

否决。每次补发都是一次完整外部调用与一次状态记录重写，链式补发使 `calls[]`、三维聚合与崩溃切点的枚举随次数增长；一次补发已覆盖实测的两类漂移，仍失败者属评审方输出不稳定，应换 attempt 或换 Profile 而非继续追问。

### P. 锁值引用件仍作清单成员（Amendment 2；已退役）

本条随锁值引用件形态于 Amendment 4 退役，原文见 Git 历史（FROZEN r4）；序号不复用。

### Q. 多候选以多请求并行代替（Amendment 2）

否决。并行只压缩等待时间，不压缩投递与评审成本，且每个成员各得一份判词、变更集内的一致性问题（成员间互引、同一触发事实的两半）无人整体评审；调用方一侧的并行形态（各轴 `review` 同时起）仍可用于不组变更集的多 subject 情形（Amendment 4 前须各轴 `--no-register` 后依次 `register`，该衔接已退役）。

### R. 档案库时代修订指称无声明自动放行（Amendment 3；已退役，S 至 V 同）

本条与原 S（回填档案库时代的 Freeze Record）、T（候选侧把指称改写为现行修订）、U（对触发本次缺口的那一轮单独关闭插件 B）、V（在受治理 inventory 内登记档案库时代修订的存在证明）五条随域一修订号核对与档案库时代修订指称的声明放行于 Amendment 4 退役，原文见 Git 历史（FROZEN r4）；序号 R 至 V 不复用。

### W. caller 自由题保留并封顶（Amendment 4）

否决（Owner 裁定 F2）。题面每轮变动是核对面与整改自伤的来源之一：题由 caller 起草、评审方对题面本身亦可开 finding（CL-34 四轮自伤的一部分来自题面）；封顶后 required 集合仍非常量，`question_assessments` 的题号核对仍随每轮输入变化。五题闭集使题从每轮输入变为契约常量，task 轮的五维度已由 `spec.md@r5 FR-21` 冻结，逐字承接零新造术语。

### X. 未改动区不阻断只写进指令、不校验（Amendment 4）

否决（Owner 裁定 F4）。只注入不校验时评审方仍可对未改动区开 `blocking`（v3 判词统计中该类占全部阻断的四分之一以上，减重第三批诊断记录），裁定 B 的分档在机械上不成立；规则 14 的代价只是评审方违规时多一次调用（原样重投、不占额度）。

### Y. 判词内新增评审方处置建议字段 `action`（Amendment 4）

否决。`no-op` / `auto-fix` / `ask-user` 一类字段是评审方的建议而非 Owner 的决定；`ask-user` 与既有 `severity = human` 同义；多一个判断字段即多一个校验面。处置决定归决定文件（§6.12），决定权留在 Owner。

### Z. 请求件级风险分档字段 `risk_tier`（Amendment 4）

否决。按对象类分档（机制正本 / 产品高风险 / 其他）属对象级默认值，其判据来源本就在交付方法 §8 矩阵；通道不应第二次定义，且它要求请求形状变更与矩阵联动。本修订只做 finding 级分档（规则 14）；矩阵重划归后续步骤。

### AA. 改读 `freeze-records.jsonl` 并保留域一修订号核对与 `archive-revision` 声明（Amendment 4）

否决（Owner 裁定 F3 甲）。台账 `repo-od-10:KB-08` 闭合条件原话的两项要求（改读 jsonl 保留核对、删 `archive-revision` 族）互斥：保留核对而删声明放行，则任何页首引用档案库时代修订的正本又重新被拒（CL-41 r1 实撞、CL-42 全部动机）；保留声明放行则须为 `.md` 记录保留记录体读取与 inventory 校验，可信边界整族随之保留。修订号核对的全部价值是拦下不存在的修订号，其代价是六轮评审与整族可信边界，而它拦下的唯一实例是一个真实存在的修订；改为只标注、由 `Q-REFERENCE` 人工核。

## 14. 最低验收场景

### S1 · 一次真实异源评审经本仓通道走通

Claude Code 会话写稿（作者集合 Anthropic），经 codex 命令行适配器选 OpenAI 或 DeepSeek 模型正式评审：preflight 通过、判词发布、四件最低成员落位（Amendment 4 前另登记 evidence-locks，已退役）、Receipt 三维为 PROVEN + SUFFICIENT + VALID。

### S2 · 资格拒绝负例

作者集合含评审方提供方 → preflight 拒绝，失败码 `eligibility`，零提供方调用，Receipt 在案。

### S3 · 信封修复正例

评审方最终消息闭栏缺失且 JSON 后有收尾散文 → 二级修复，发布判词满足严格文法，Receipt `extraction.tier = repaired` 且记录 `missing-closing-fence` 与 `trailing-content`，发布块内 JSON 值区段字节与原始消息中的区段相同。

### S4 · 补发轮正例与负例

评审方 JSON 截断 → 同一 attempt 内补发调用取得有效机读块且交叉核对通过 → attempt 分类 `completed_with_valid_verdict`、`extraction.tier = reemitted`、`reemit_trigger = envelope`；补发块 finding 集合与原正文不一致 → 整体 INVALID。**校验类**（Amendment 2）：机读块完好而缺 `verdict_schema` 与 `authorization_disclaimer`（已知值缺陷）→ 补发后 VALID、`reemit_trigger = validation`、`reemit_reasons` 列出两项、`reemit_unverifiable_fields` 为空数组；机读块完好而叙述 finding 标题不按 `### <id> · <severity> · <title>`、节名非逐字、物理第 2 行不是 Human decision 行（叙述缺陷，CL-39 r2 实撞形态）→ 补发后 VALID、`reemit_trigger = validation`；两类同时在场 → 一次补发同时修复；补发块改动任一 finding 的 `severity` → `reemit-invariance-mismatch`、`mismatched_fields = ["findings"]`；机读块缺 `question_assessments`（判断字段缺陷）→ 不补发、`verdict-invalid`、`calls[]` 恰一项；补发后叙述仍缺 `## Question assessments` 节 → `verdict-invalid` 且 `reemit_trigger = validation`、无第三次调用。

### S5 · 轮次额度到额停报与加轮

Registry 缺省额度（2，Amendment 4）下同轴 r1、r2 各已发布 tracked Receipt 后投 r3 → `round_budget_exhausted`、退出码 1、stderr 报告含已投递轮数、允许轮数 2、末轮 blocking finding 条数与加轮方式（追加 `request.round_extensions` 的 Human 授权记录）；追加 `round_extensions` 一条后同一请求放行；再到额再拒、再加再放（至少两次循环）。到额三出口的另两条（带保留 re-Freeze / 带保留判 done、退回）不经通道，其形态见 §6.10 与 S25。

### S6 · 逐轮关闭与改选

r2 经 review-skip 关闭，r3 指向 r1 判词继承并显式换 Profile → Receipt 记 `selection_source = explicit-request` 与差异；缺 review-skip 裁定时 `round-gap-unexplained`。

### S7 · Anthropic 模型评审路径

Codex 会话写稿（作者集合 OpenAI），经 §7.3 或 §7.4 的 Anthropic 路径正式评审并产出受治理判词；或探针证据在案并附 Owner 对路径的裁定（Definition Acceptance Criteria 第四条二选一）。

### S8 · 直接接口与聚合商正式档

经 http 适配器对 DeepSeek Official 一次正式评审；经聚合商一次评审，应答模型标识命中 `registered_equivalents` → `profile_binding = SUFFICIENT`、受治理判词。

### S9 · 新增一种评审方运行时的改动面

以固定补丁新增一个假适配器：只动一个适配器模块、其自测声明与 Registry 条目；契约模块、契约常量、适配器接口模块零改动（机械 diff 验收，gates 设计 S4 同形；成立前提 = §5.2 数据驱动发现）。

### S10 · 改轮次额度默认值

只改 Registry 一个数字，代码零改动，S5 场景按新值复现。

### S11 · 工具版本变化不提醒

同一 Profile 两轮分别在不同工具版本下运行：两轮均放行，preflight 输出与 stderr 无差异提示，Receipt `runtime.changed_across_rounds = true`。显式改选到另一适配器（如 codex → 直接接口）：本轮 `runtime` 只含 `api_endpoint_id`、`changed_across_rounds = true`，同样无提示。同一 attempt 内补发调用的版本与首次不同：`runtime.tool_version` 取首次值、`changed_within_attempt = true`，同样无提示。

### S12 · 证据体积对照

同一任务的任务定义评审一轮，借用通道时期与本仓通道各取一轮，四件最低成员行数与字节数对照在案，下降幅度与 §8.3 所述三处来源可对应。

### S13 · 自测可红可绿与变异验收

自测全绿；变异清单逐条施加后对应负例逐条红；零工作树副产物。**Amendment 1 新增变异项**（R1-B6 整改）：把域一匹配改为全仓匹配、把零命中判定改为相对全仓而非相对选定域、以 `inputs.references` 交集消解域内多命中、把投递名去重的比对面由整束已占用集合缩回同基名组、在注入文本中把任一必填字段由字段行改回标题句、从某字段行内删去一个嵌套必填成员名、跳过来源路径的前置去重、把保留前缀禁令一并施加于禁名表改写结果、把规定落点排除放宽到首段所指顶层成员已存在的情形、取消规定落点的声明前置改回自动放行、把 `D-<NN>@rN` 形态纳入候选引用提取集、把规定落点声明的判据由 `kind` 逐字等于 `planned-location` 放宽为 `reason` 含任意文本、允许 `evidence_limits[]` 内同一 `reference` 出现多项、把计划交付文件的前缀比较由完整单元目录加 `/` 改为首段相等、允许 r1 携带 `previous_round`、以及把成员名序列的校验深度限为一层——各项施加后对应负例须逐条红。**Amendment 2 新增变异项**：把校验类补发的触发扩到判断字段缺陷、把判断字段的逐字节相等核对改为只核对 finding id 集合、允许第二次补发、从注入骨架删去任一骨架行、把骨架的题号行改为不逐题渲染、把 `candidates` 的精确等集校验放宽为子集、允许任务轴多候选、把 `candidates` 的次序核对退回只核首项、把多候选基线改为只取首候选、允许 `scope_files_read` 含未投递的仓内路径——各项施加后对应负例须逐条红（Amendment 2 与锁值引用件绑定的变异项随其形态于 Amendment 4 退役）。**Amendment 3 新增变异项**随域一修订号核对与档案库时代修订指称于 Amendment 4 整族退役。**Amendment 4 新增变异项**：把五题闭集的题号核对放宽为子集、按另一 stage 取套、删除规则 14 或把 `unchanged_region` 的 `blocking` 放行、把规则 14 的失败归入可补发项、把 r1 改动区改为不渲染、把首冻候选改为判失败码、把 `max_rounds` 字面量写回代码、把决定文件的 finding id 等集校验放宽为子集、免除 blocking `skip` 的 `work_item`、允许 `owner_verbatim` 为空、跳过 `verdict_sha256` 绑定、把 `decisions-missing` 改为静默放行、把处置段核对放宽为只核在场、把派生残留项核对放宽为只核 id、把现行修订号标注改回拒绝不在案修订号、在注入文本或叙述行正则内保留 `exhaustive`、把运行时身份资格检查加回，各项施加后对应负例须逐条红。

### S14 · 引用缺件三分负例

被审对象引用一个不存在的路径、一个歧义裸文件名、一个存在但未投递的正本，preflight 分别以 `reference-unresolved` / `reference-ambiguous` / `reference-missing` 拒绝；对档案库文件的豁免声明放行。**解析域等价类**（Amendment 1；R1-B6 整改）：其一，规划基线件裸名带修订号后缀、域一内恰一命中而域三内多命中——放行，且投递的是域一那件；其二，同一裸名在选定域内零命中而域外存在同名文件——判 `reference-unresolved`，失败说明列出域外同名命中但该列举不改变结论；其三，域三内多命中且命中集合与 `inputs.references` 的交集恰一件——仍判 `reference-ambiguous`（消歧规则已于本次修正删除，交集不参与判定）；其八（Owner 2026-09-04「域四删」后重述），被审对象含 `D-<NN>@rN` 形态——该串不进入提取集：任务书「引用解析结果」节不列出它，通道不判任何失败码，束内是否含该 Decision 文件或其治理流水不改变结论（正例）；变异「把该形态纳入提取集」施加后，本例因 Decision 文件未投递而判 `reference-missing`、或因 ID 无对应文件而判 `reference-unresolved`（负例）。其七（本次新增；R27-B2 收窄、R28-B2 改为声明式、R29-B2 给出 `kind` 文法），**经 `evidence_limits` 以 `kind` = `planned-location` 声明为规定落点**且两项校验俱成立（首段命中仓根闭集、该顶层成员本身不存在）——放行并在任务书按「声明为规定落点」列出；**未经声明**的同形态路径——仍判 `reference-unresolved`（自动放行已取消）；已声明但首段所指顶层成员**已存在**——声明无效，判 `reference-unresolved`（普通缺件）；已声明但首段不在闭集内——声明无效，同判；首段命中闭集且路径存在为目录——按既有 directory 处置放行，无须声明；同一路径列入 `evidence_limits` 而 `kind` 缺省或为 `exemption`——不构成规定落点声明，两项校验不执行，任务书按豁免而非按规定落点列出；`kind` 取闭集外的值——请求文法失败，preflight 拒绝；同一路径在 `evidence_limits[]` 内出现两项（一项 `planned-location`、一项 `exemption`，或两项同 `kind`）——请求文法失败，preflight 拒绝，不进入引用解析（R30-B1）。其四，`rules_catalog.json` 缺 `top_level_members` 键，或其中缺域一、域二**两个目录名之任一**——判 `root-closure-unavailable`，不回退到全仓匹配（两名各一负例）；其五（R2-B5 整改；Amendment 4 改写），域一路径与裸名命中，无论引用的修订号是否在案均放行，任务书并列标注引用修订号与投递字节的现行修订号（取自 `freeze-records.jsonl` 末行或编号最大的 `.md` 记录，该路径在任何 subject 冻结事实内零命中时标注不可得）；`reference-revision-unknown` 不再判出（等价类的旧形态见 S27）；其六（R2-B5 整改），域二的完整基数三例——单元目录下零命中、恰一命中、两个不同单元目录下同名各一命中（判 `reference-ambiguous`），另含深度负例：命中位于 `<域二目录名>` 下两层以上而非恰一层单元目录内，不计入域二匹配集。其九（R29-B3 整改），计划交付文件的边界四例——候选单元目录之下的不存在路径归为计划交付文件、放行；与单元目录仅共享首段、或目录名仅为单元目录名加后缀的兄弟目录之下的不存在路径——判 `reference-unresolved`（证明比较取完整单元目录加 `/` 为前缀）；其他已存在顶层成员之下的不存在路径——判 `reference-unresolved`；候选位于仓根时——无单元目录，任何不存在路径均判 `reference-unresolved`。**其十（Amendment 2）锁值引用件**的全部等价类随其形态于 Amendment 4 退役（原文见 Git 历史，FROZEN r4）。

### S15 · 复审六项映射

r2 任务书含整改声明（以处置段起始）、上一轮决定摘要与本轮 Profile，被审输入含 `previous--` 族固定投递名（3 + 候选数件；每候选基线名 `previous--candidate-baseline--<上一轮投递名>`，Amendment 2）且哈希与上一轮 Receipt / 清单一致；缺上一轮 Receipt 时 `inherit-unanchored`；本轮候选来源路径集合与上一轮不等时 `inherit-unanchored`；缺上一轮决定文件时 `decisions-missing`（Amendment 4，S26）。**轮次约束负例**（本次新增，补 `request-field-not-allowed` 此前有引入无场景的缺口）：r1 携带 `previous_round` —— 判 `request-field-not-allowed`；r2+ 缺该字段 —— 判原有必填缺失码。

### S16 · 两轴端到端

同一候选分别以任务轴（`task_record` 在场）与 subject 轴（缺席）各走一次 preflight 至提交：派生的 `tracked_round_dir` / `attempt_round_dir` 与布局权威 §7 一致，计数、文件锁、提交与清理只消费派生值。

### S17 · 投递名整束全局唯一（Amendment 1）

一束内同时含：两件同基名不同目录的参考件、一件基名命中禁名表的参考件、一件基名恰等于任务书投递名的参考件、一件来源路径段自身含 `--` 的参考件，并在 r2+ 场景下叠加 `previous--` 族复审固定名。全部投递名两两不等，且除禁名表动作生成的 `source--<原名>` 外，**任何投递名（含初始基名与逐段扩展结果）均不以保留前缀起始**（见 §6.2 第 4 条）；清单 `inputs[].source` 可逐件反查来源；同一组来源路径以不同列表顺序提交两次，派生结果逐字节相同。另含三例：根级禁名件（来源路径只有一段且基名命中禁名表）得 `source--<原名>` 并放行，保留前缀禁令不施于该结果（R2-B5 整改）；来源自身基名即为 `previous--<某名>` 或 `source--<某名>` 时，即便无精确重名冲突也不得以该初始基名通过，须按冲突处置进入逐段扩展（R24-B4 整改：两个前缀因此形成隔离命名空间）；同一来源路径在被审输入内列两次，在派生之前即判 `duplicate-reference-source`，不进入逐段扩展。负例：路径段取尽仍无法区分的构造判 `bundle-name-collision`。

### S18 · 判词对投递名的消费（Amendment 1）

在投递名经去重派生而不等于基名的束上走完一轮：判词 `findings[].location.file` 与 `scope_files_read[]` 取派生后的投递名即通过校验（§6.5.2 第 9 / 10 条）；取来源路径或取未派生的基名即判 INVALID。本场景证明去重派生与判词契约的既有校验相容。

### S19 · 冻结件修正的送审形态（Amendment 1；R2-B5 整改；变更集的多候选形态见 S20）

对一件受锁设计正本的修正走一轮完整评审：请求 `subject` 取该受锁对象的 subject、`inputs.candidates` 恰列该设计正本一件（v4 文法，Amendment 4 前为 v3；判词 `candidate` 即该件，R35-B2 整改）、其 Changelog 与其余成员作 `reference` 同束投递（交付方法 §7.6「各受锁成员逐件为候选、其余成员作参考件同束投递」）。终轮 Receipt 的束清单内 role 为 `candidate` 的成员哈希，恰含该受锁对象的新冻结字节，freeze-record 设计 §5.3 的相等断言 C1 因此成立。**负例**：以 Changelog 为 `candidate`、受锁设计正本仅作 `reference` 的束——受锁字节不出现在 `reviewed` 中，C1 在 re-Freeze 时判红；本设计 r1 与本次修正的前两轮评审即以该错误形态执行（`repo:KB-01` addendum 登记），本场景把该形态固化为负例。

### S20 · 多候选变更集评审（Amendment 2；subject 轴）

一个交付方法 §7.6 变更集含两个 subject 各一件字节变化的受锁成员：请求 `subject` 取变更集轴（先例轴名形态 `changelog-<change-identity 小写>`），`inputs.candidates` 恰列两件受锁候选、Changelog 与其余成员作 `reference`，一轮一次投递、一份判词；判词 `candidates` 为两件身份的精确等集、`candidate` 等于首件；两个成员的 Freeze Record 各以同一轮为 `review_anchor`（`review_subject` = 该轴），freeze-record 设计 §5.3 C1 对两件受锁字节各恰一命中、其 §8.1 读取约定的 `candidate.sha256` 属候选集合。r2 时被审输入含两件 `previous--candidate-baseline--<投递名>`，任务书差异节两小节。负例：`candidates` 只列一件——判 INVALID（§6.5.2 第 8 条）；r2 的 `inputs.candidates` 少列一件——`inherit-unanchored`；`task_record` 在场而 `inputs.candidates` 列两件——请求文法失败、preflight 拒绝（任务轴恰一件，§6.2 第 1 条；R33-B1）。同一 subject 两件受锁成员同时变化（设计正本与其受锁工具件）按同一形态走通，交付方法 §7.6 的单候选限制自此解除。

### S21 · 锁值引用件的一轮走通（Amendment 2；已退役）

本场景随锁值引用件形态于 Amendment 4 退役，原文见 Git 历史（FROZEN r4）；场景号不复用。

### S22 · 档案库时代修订指称的声明放行（Amendment 3；已退役）

本场景随该形态于 Amendment 4 退役，原文见 Git 历史（FROZEN r4）；场景号不复用。

### S23 · 五题闭集校验（Amendment 4）

task 轮与 impl 轮各一份评审请求（`review-channel-request/v4`，不含 `questions`）：注入文本与任务书第 8 节的题号集合恰为该 stage 五题；判词 `question_assessments` 恰含五题各一条 → 校验通过；缺 `Q-REFERENCE`、多出 `Q1`、`Q-CHANGE` 重复两条、impl 轮取 task 轮五题，各判 INVALID（§6.5.2 第 2 条）、不补发、`calls[]` 恰一项。旧判词（`verdict_schema` v3、题号 `Q<n>` / `STD-<n>`）经 `parse_published` 仍可读出 `verdict`（handoff-protocol §4.2 锚不受影响）。请求件含 `questions` 或 `standard_questions` → 请求文法失败、preflight 拒绝。

### S24 · 未改动区阻断判 INVALID、原样重投不占额度（Amendment 4）

r1 任务书改动区列出候选的差异块；评审方判词含一条 `origin = unchanged_region` 且 `severity = blocking` 的 finding → `verdict_validation = INVALID`、`verdict_problems[]` 含 `rule-14:<id>`、attempt 分类 `reviewer_output_invalid`、失败码 `verdict-invalid`、无补发、tracked 目录无任何成员；caller 请求件一字不改再投同一轮 → preflight 通过（已投递轮数未增，§6.10）；评审方改判该 finding 为 `non_blocking`（或 `human`）→ 校验通过；同一 finding 取 `origin = changed_region` 且 `blocking` → 校验通过。

### S25 · 封顶两轮到额与三出口（Amendment 4）

Registry 缺省额度 2：同轴 r1 FAIL、r2 FAIL 各已发布后投 r3 → `round_budget_exhausted`（S5）；出口其一，请求件追加 `round_extensions` 一条 Human 授权记录 → r3 放行；出口其二，Owner 带保留 re-Freeze 或带保留判 done → 不经通道，冻结记录行 `exit = freeze-with-reservation`（freeze-record 设计 §5.1）或 `done` ruling 记保留，通道对该轴无任何动作；出口其三，退回 → 不经通道。三条出口不新增任何通道字段或产物；`cst-review` 与 `HANDOFF/README.md` 转录三出口的指令词。

### S26 · `respond` 三动作与 r2 派生核对（Amendment 4）

r1 判词含 `R1-B1`（blocking）、`R1-N1`（non_blocking）、`R1-H1`（human）三条 finding。`respond` 输入对 `R1-B1` 取 `fix` 带 `instructions`、对 `R1-N1` 取 `skip` 带 `work_item`、对 `R1-H1` 取 `approve`，三条各带 `owner_verbatim` → 决定文件写入 `attempt_round_dir/decisions.json`，`verdict_sha256` 等于 r1 判词字节、stdout 含处置段（三行、次序同判词）与派生残留项 `RES-1`（title · work_item）；r2 请求件 `remediation_statement` 以处置段起始、`accepted_residuals` 含 `RES-1` → preflight 通过，任务书第 3 节含决定摘要，Receipt `decisions_sha256` 在场。负例：`R1-B1` 取 `skip` 而无 `work_item` → `decisions-invalid`；决定文件缺 `R1-H1` 一条 → `decisions-invalid`；`owner_verbatim` 为空 → `decisions-invalid`；r2 请求件删去处置段、或 `accepted_residuals` 缺 `RES-1`、或上一轮判词在 `respond` 之后被替换（`verdict_sha256` 不等） → 各判 `decisions-mismatch`；决定文件缺席 → `decisions-missing`；r1 请求件不受决定文件约束。

### S27 · 现行修订号标注只标不拒（Amendment 4）

被审对象引用 spec.md@r2（该规划基线件本仓在案记录自 r4 起，早于现行修订）、spec.md@r6（等于现行修订）与一个不在案的修订号（如 spec.md@r99；本例刻意不以反引号标注，理由同 §6.2 规定落点段）：三条引用均放行，任务书「引用解析结果」节逐条并列引用修订号与投递字节的现行修订号（spec 的现行修订号取自 `records/governance/spec/` 内编号最大的 `.md` 记录，`freeze-records.jsonl` 在场的 subject 取其末行）；不判 `reference-revision-unknown`、不读任何登记本；请求件不需要也不接受 `archive-revision` 声明（`kind` 表外值即请求文法失败）。反例断言：以 r4 的判定（拒绝 spec.md@r99）为变异施加后本例须红。引用一个在任何 subject 冻结事实内零命中的域一路径 → 标注「现行修订号不可得」、不判失败码；subject 目录名既不等于单元目录名也不等于文件名去扩展名的规划基线件（本仓 milestones.md 的 `.md` 记录在 `records/governance/milestones-fused/`）在其 `freeze-records.jsonl` 出生前同样标注不可得、同样放行（§6.2 第 2 条反查的候选 subject 名闭集）。

### S28 · r1 改动区差异节（Amendment 4）

对一件已冻结的设计正本的修正候选投 r1（本修订自身即首个实例，`preflight` 零提供方接触）：任务书第 3 节「改动区（通道算）」在场，基线 SHA-256 等于该 subject 现行冻结事实内该路径的 `sha256`（`.md` 记录取 `frozen_objects[].sha256`），差异块至少一个、每块列基线行段与候选行段；r1 被审输入不含 `previous--` 族；首冻候选（任何 subject 冻结事实内无其路径）→ 任务书声明整件为改动区、不判失败码；身份在案而 attempts 封存副本与 Git 历史均无该 SHA-256 的 blob → `baseline-unrecoverable`。

### S29 · 历史轮计数与继承

完整轮退出 HEAD 后，额度、最大轮号、task/impl 分开及 subject 原序列保持；同路径同身份只计一次。Receipt/manifest/Verdict/候选基线逐项篡改、跨 commit 拼轮、旧 schema 不兼容各自拒绝；旧 schema 的已发布轮仍计数。固定来源表纳入任务书身份。

### S30 · 历史发布与恢复

已退出轮不能重新发布或覆盖，preflight 和 rename 前均核；并发存活、generation 及原 no-overwrite 场景回归。Receipt 只回链原 attempt，缺 decisions.json 不推导 Owner 决定，respond 可处理验证过的历史轮且只写 ignored 层。

### S31 · 输入边界与能力凭据

候选缺失不历史回退，裸名域不扩大；历史引用仍过秘密/大小/封存检查；版本冲突、坏路径、缺 helper/source 明确拒绝且 provider 调用次数为零。当前 Registry 仍须三方相等，r31 实际凭据在场，历史继承不代替 capability 校验。

上述为新增施工验收要求，本次设计冻结未执行。

## 15. 反思

### 必须现在定（本设计承载）

- 契约层与适配层分离，产物零调用工具名词：不定则「加一家评审方」永远等于改契约。
- 判词机读块为正本且发布文档恒满足严格文法：不定则每个读端都要各自实现一份包容逻辑。
- 包容只裁信封不改 JSON 字节，本体坏则同一评审方补发：不定则「包容」会滑向替评审方改判断。
- 能力绑定元组不含版本、契约哈希不作继承门：不定则每次工具升级与每次 amendment 都重演档案库的重绑定与重选。
- 任务书事实段由通道渲染：不定则手写事实错误这一最大问题类无法结构性消除。
- 轮次额度到额只停报、加轮无限：不定则要么无上限、要么通道被断路器关死。

### 同类潜在坑一并封住

- 「配置被接受但静默忽略」一律非法（档案库 R3-B4 的教训）：`--no-reemit` 记入 Receipt（`standard_questions` 与 `--no-register` 已随 Amendment 4 退役，无静默面）。
- 引用型字段必须机械可解析：`previous_round`、`receipt_ref`、`accepted_residuals` id 均在 preflight 解析并比对。
- 通道不在失败路径含任何改选逻辑（继承 no-fallback 的强形态）。
- 补发轮限定同一 Profile：换 Profile 补发等于换评审方，破坏异源判定的单一性。
- 直接接口不分片：分片会使评审方看不到完整被审输入而仍出判词。
- 同轮文件锁（内核随持有者进程终止释放，不存在死锁清理）与 no-overwrite 双防线：**同一工作树内**两进程同轮派单只能成功一个；跨 worktree 不在保证面（§8.2 威胁模型其二、§15 残留）。

### v1 可接受残留

- 模型提供方与底层模型身份仍是 operational claim；直接接口的应答模型标识也只是提供方自述。
- capability 证据的最终信任边界是 Human 提交纪律：`receipt_commit` 锚定使工作树篡改不可能通过，但伪造整套 Receipt 并提交属人为越权，留完整 Git 痕迹，超出机械门职责（档案库 runner 设计 §19 同款残留的继承）。
- 评审方模型漏检无结构解法（档案库 OD-64、KB-39）；常设问题集降低但不消除。
- 调用工具适配器下「运行时接受配置却不遵守」不被观察（档案库 KB-37）；关闭路径 = 解析 codex 事件流中的命令事件作工具面核验，属独立立项；直接接口路径无此残留。
- 调用工具子进程的其他出口（如 shell 网络连接）不受通道机械约束，属沙箱行为（档案库 OD-41b）。
- 提交协议的威胁模型（§8.2）不含同一工作区内非通道进程在协议期间对 tracked 目录的改名、替换或写入；唯一的机械暴露面是「目标核对与 rename 之间出现的空目录会被 rename 替换」，这只能由该类越界写入制造，由 Git 历史与 Owner 合并审查事后暴露（`locks` 门已退役），通道不做防御，如实登记为残留。
- 跨 worktree 的同轮互斥不在保证面：同任务由 `D-09@r1` 三绑定排除双写者；subject 轴跨 worktree 同轮（两个任务的会话各自对同一 subject 同一轮发起评审）可各自成功发布，由 MR 合并时的同路径冲突暴露、Owner 裁定取舍，如实登记为残留。
- 同轮文件锁依赖运行时文件系统的 `flock` 语义：网络文件系统不在保证面；同一工作树内非通道进程删除或替换 `.in-progress` 属威胁模型外事件（§8.2 其一），可使两个持有者各锁不同 inode，与直接编辑证据文件同级，由 Git 历史与 Owner 合并审查事后暴露。
- 内联投递的容量守卫按字节而非 token 估算，保守；超大被审对象走调用工具适配器。
- Anthropic 路径的具体形态待探针，本设计只冻结要求（§7.3）。
- 术语「被审输入」与上游 delivery-method 的「束」并存（task-artifact-schema 已随减重第 5 步退役，其用词随之消失），对照在 §3 一次成文；上游用词更正走其 amendment，不在本设计面。
- 补发轮只能证明叙述正文可恢复字段的不变性；`reemit_unverifiable_fields` 所列字段只有补发一方的自述（§6.5.4），读端可据 Receipt 判断是否采信。
- 校验类补发（Amendment 2）下叙述的结构行由通道自机读块渲染并要求逐字采用，叙述不再是机读块的独立来源；Receipt `reemit_trigger = validation` 如实标记。判断字段与原块逐字节相等使补发无法改判断，评审方原叙述的推理文字由评审方自行搬入骨架、通道不核对其内容。
- 改动区的判据止于差异块（Amendment 4）：`findings[].location.anchor` 是自由字符串，通道不能把一条 finding 映射到某个 hunk，`origin` 由评审方自报、规则 14 只核对自报值的组合；后续若要机械核对，须先把 `anchor` 改为行号或标题路径文法，属下一次 amendment（台账登记见 CL-44 第 5 项）。
- 域一引用的修订号写错不再被机械拦下（Amendment 4，F3 甲的残留）：通道只并列标注引用修订号与现行修订号，由 `Q-REFERENCE` 交评审方人工核。
- 决定文件的写入口只有 `respond` 终端形态（Amendment 4）：Owner 原话经执行者转录进 `owner_verbatim`，转录的忠实性无机械核对；审阅页面作为另一写入口尚未出生（§16）。
- Amendment 2 的锁值引用件残留与 Amendment 3 的档案库时代修订指称残留随两形态于 Amendment 4 退役，原文见 Git 历史（FROZEN r4）。

## 16. 明确不决定

- Anthropic 评审路径三候选的最终取舍（施工期探针后作为本设计 amendment 输入）。
- 各提供方的具体模型目录、`max_input_bytes` 取值、费用与配额。
- 自测接线进 CI 的时点（KB-36）。
- 逐条核对的机械看守（gov-t11）、Policy Gate 评估（feature-t6）、证据分层缩面（gov-t9）。
- 中心 orchestrator 对通道的调用形态（M-04）。
- gov-t5 Freeze Record 设计对 §6.11 `vendors` 表的改指时点（属 gov-t5 的 amendment）。
- 审阅页面与反馈队列作为决定文件的另一写入口（Amendment 4；增强规划，台账 `repo:OD-10`）：本设计只定 `review-channel-decisions/v1` 文法与 `respond` 终端形态，页面、队列与服务不在本设计面。
- delivery-method §8 评审矩阵按风险分档的对象级默认值重划（Amendment 4 只做 finding 级分档，§6.5.2 第 14 条）。
