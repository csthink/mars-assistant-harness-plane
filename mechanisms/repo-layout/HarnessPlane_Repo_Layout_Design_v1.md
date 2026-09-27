# HarnessPlane 仓库布局参考设计（新仓目标布局）

> Depends on:
> `milestones-fused.md@r1` gov-t0
> `spec-fused.md@r1` FR-05、FR-50、NFR-09
> `sdd/proposal.md`
> `HarnessPlane_MVP_Rolling_Delivery_Method_Design_v1.md`
> `HarnessPlane_Freeze_Record_Design_v1.md`
> `HarnessPlane_Repo_Architecture_Design_v1.md`
> `HarnessPlane_Mechanism_Replication_Diagnosis_2026-08-19.md`
>
> 权威状态: subject `repo-layout`（治理记录目录按所在仓的布局规则解析；唯一状态正本）

CL-55 候选：拟修订 r12，语义级；原冻结基线 r11。本次仅起草，未送审、未 re-Freeze、未启用。完整变更集见 changelog/CL-55-review-evidence-local-archive.md；当前权威仍按 records/governance/repo-layout/freeze-records.jsonl 解析。

最近已冻结基线（历史）：FROZEN r11，2026-09-08，CL-52 语义级变更集。Owner 已核差通过并授权共同 re-Freeze；冻结事实 = `records/governance/repo-layout/freeze-records.jsonl` 内 revision 11 的记录。本次只冻结规则，历史读取与 HEAD 退出能力仍须完成 repo-layout §7.4 的施工与启用条件，不构成施工或删除授权。

前序冻结（历史）：FROZEN r10，2026-09-07，CL-50 第 6b 批语义级 amendment。Owner 已核差通过并授权共同 re-Freeze；冻结事实 = `records/governance/repo-layout/freeze-records.jsonl` 内 `revision 10` 的行。改动范围与已裁例外见 `changelog/CL-50-engineering-documents-and-prototype.md`。

前序冻结（历史）：FROZEN r9，2026-09-07，CL-48，第 6a 批产品基线与存量项目接入。前序冻结 r8；本修订区分下游接入骨架与本仓创始落位，对齐四件来源与模板直接消费者，不新增目录成员、不实施第 6b 批。Owner 已核差通过并明确授权与同批产品基线 re-Freeze，Changelog = `changelog/CL-48-product-baselines-and-brownfield.md`。

最近已冻结修订（历史）：FROZEN r8，2026-09-07，变更集 `changelog/CL-47-optional-governance-lint.md`。Owner 已核差通过、接受本次次序偏离，并授权本变更集 re-Freeze；冻结事实 = `records/governance/repo-layout/freeze-records.jsonl` 内本次 `re-freeze` 记录。修改只覆盖 layout / manifest 可选化及直接消费者，原第 6 步范围不在本次展开。

前序冻结修订说明（历史）：本修订（FROZEN r7，2026-09-07）= Amendment 6，Changelog = `changelog/CL-45-artifact-templates-and-schema-retirement.md`；触发 = Owner 2026-09-07 裁定 J7 / J12 / J14（台账 `repo:OD-10`；对齐欠账 = 台账 `repo-od-10:KB-11`）；对齐级、语义零变化：页首删已退役的 task-artifact-schema 依赖；§5.1 / §5.2 / §6.2 / §6.6 / §8 / §11 S11 与 S13 / §15 内指向已退役机制（四类工件 schema 设计正本、`cst-freeze`、锁转换授权句、登记本看守、旧 freeze-record 节号）的指针与断言改为冻结记录行形态与 `mechanisms/artifact-templates/` 模板集指针；条目文法、卷形制、单元文法与事实归属表的语义零改动。此前修订 = Amendment 5（FROZEN r6，2026-09-05，`changelog/CL-39-freeze-record-single-record-and-ritual-tool.md`）。

## 1. Purpose

CL-60 已按 Owner 明确指令在本任务分支 re-Freeze r17，核差形态为 owner-review；冻结事实以 `records/governance/repo-layout/freeze-records.jsonl` 内 revision 17 的记录为准。原始受审候选见 `records/diagnostics/assistant-hp/2026-09-21/candidate-map.json`；采纳时仅同步状态文字，逐字差异与正式身份见同目录 finalization-results.json 和 finalization-metadata.patch。下方前序候选与已冻结说明按形成时点作为历史读取。本次定稿不授权产品开工、真实模型调用或发布。

CL-59 已按 Owner 明确指令在本任务分支 re-Freeze r16，语义级，核差形态 owner-review；现行冻结事实 = records/governance/repo-layout/freeze-records.jsonl 内 revision 16 的行。原统一执行器要求由 skill-only 规则替换，运行与安装状态见 HANDOFF/README.md；CL-58 原始决定和对象身份保留在原记录及 records/diagnostics/publish-closeout/2026-09-11/finalization-results.json。下方前序候选说明按其形成时点读取；本次候选到终裁的身份核对见 records/diagnostics/publish-closeout/2026-09-11/skill-only-finalization-results.json。

CL-56 正式候选：拟修订 r13，原冻结 r12，语义级；起草依据 HANDOFF/progress/repo-od-10.md:668。本文件是 candidate-map.json 指向的正文候选，未生效；现行权威按正式路径及治理记录解析。下方前序候选/冻结说明均按原时点作为沿革读取。

定义唯一交付仓 `csthink-harness-plane` 的目标物理布局（蓝图）。它是融合产品线一切后续交付的落点权威：gov-t1 据之落骨架与创始三实例，gov-t2 据之重建门，既有 UI lineage 据之保留历史落点，gov-t13 据之取载荷边界。本设计回答四个问题：

1. **机制单元怎么住**——一个机制单元（设计正本 + 可执行物 + 测试用例 + 素材）一个目录；新增一道门或一条纪律等于在指定位置增加一个目录（终结旧仓「一个单元的身份散落约十处、跨六个顶层目录」的形态，诊断 §3.13——新仓从第一天起不复现它）。
2. **三区与目录如何对齐、载荷边界在哪**——机制区 / 实例区 / 证据区各有物理边界；本仓对安装包载荷的贡献按目录取整（FR-05 的目录化）。
3. **单线实例住哪**——融合终裁（OD-55/56）后只有一条产品线：规格链创始三件住 `sdd/`（OD-81），任务记录、Decision、UI lineage、治理记录、评审证据各有唯一落点；仓根收敛为纯机制契约闭集（成员固定、不得私自增补的名单）。
4. **证据各类存储落何处** - Git 正式记录、本机耐久归档及备份、本地暂存的物理边界（FR-50，切换见 §7.5），关键原件不能只存在于暂存目录。

**与旧稿 v1 的使命差异**：v1 是旧仓 `harness-plane-governance` 的原地改造蓝图（含迁移对照表与跨区字节数与 SHA-256 校验值解析）。融合终裁后旧仓整体转档案、零迁移（OD-56：治理链从零重建、旧权威不搬运），该使命随之收束；本稿以同一 subject 承载新使命——**新仓目标布局**。新仓从零建立，没有迁移账，这是本稿比 v1 大幅缩短的原因，不是覆盖面缺失。

## 2. Scope

本设计冻结：

- 新仓顶层目录文法与三区↔目录对齐关系（§4）；
- 机制区单元目录文法与登记派生规则（§5）；
- 实例区各落点：`sdd/` 规格链、`tasks/`、`decisions/`、`changelog/`、authority 目录、ui 目录、`records/`、`HANDOFF/`（§6）；
- 证据分层的物理落点与 Git 跟踪边界（§7）；
- 仓根受跟踪成员闭集与按需建立成员的建立事件（§8）；
- 本仓对分发载荷的贡献边界（§4，FR-05 落点化）与下游产品线仓骨架的关系声明（§9）。

本设计不设计或施工：

- 新仓任何真实目录、文件的创建与创始实例落位（gov-t1，独立任务独立授权）；
- 门与校验器的重建设计（gov-t2）；登记机制与锁机制的**存在与形制**归 gov-t17（本设计只规定其区域级落点为 `records/` 根，不预设文件名与载体格式）；
- 四类工件共用的实例首冻定位基准形态（gov-t4），以及 proposal / spec / milestones / task 的现行模板与 ruling 模板（`mechanisms/artifact-templates/`；gov-t19 / gov-t20 / gov-t21 / gov-t22 原物理 schema 已退役，历史治理事实保留）；Freeze Record 物理形制（gov-t5）、Decision 机制重建（gov-t25）、交接协议重建（gov-t26，已交付）、评审通道重建（gov-t8）、实际日志与治理时间线的形制（feature-t15；gov-t10 暂停事实与原计划留作历史，见同批 milestones r13）、分发载体与打包工具（gov-t13）、Agent 指向性适配件的物理形态（gov-t14）；
- apps 目录 区内部文法与技术栈（M-04 首个代码任务与届时公共 Decision）；独立代码仓（若未来经 C-10 选项集 Decision 建立）的内部结构；
- 旧仓 `harness-plane-governance` 的任何改动（整体档案，零迁移）。

## 3. 布局总则

### 3.1 单线原则：仓根即产品线

融合终裁取消了治理线实例四件（gov-proposal 等第二套 Layer 3 实例）；`gov-` 只是任务类型前缀，gov 任务与 feature 任务同为产品交付（`milestones-fused.md@r1` §1 类型映射声明）。因此新仓**不存在线目录**：v1 的 `<line>/` 线文法、`product/` 与 `gov/` 并列结构随前提失效，产品线的实例直接由顶层目录承载。顶层目录一律按**内容物类型**命名（如 `sdd/` = 规格链工件），不按线身份命名。

### 3.2 组织公理（承 v1，按单线修订）

1. **区随目录、根纯机制**：每个顶层目录整体属于一个区（机制 / 实例 / 证据）；仓根受跟踪文件收敛为纯机制契约面（闭集见 §8），实例零居留。声明例外两处：① 任务目录内的 `reviews/` 与 `attempts/` 子树（证据区嵌在实例区内——两轴分流语义，参照旧 repo-architecture Rejected D，融合线维持）；② 各家 Agent 适配目录（.claude 目录 等）属三区之外的非治理便利层（proposal §5 此前已裁定语义；纪律与校验见 §5.2）。两处例外均不影响打包：实例区整体不入包，适配目录不入载荷本体。
2. **单元同居**：一个机制单元的设计正本、可执行物、selftest、配置与素材同住一个目录；单元内部形态由各单元权威自定，本设计只定单元边界与位置。
3. **登记靠派生**：单元名即 subject 名。一个单元的治理记录住 `records/governance/<单元名>/`，评审证据按 `reviews/<单元名>/` 派生逻辑身份，切换后物理原件住 §7.5 仓外归档 - 由名字派生，不靠逐处登记发现。新仓从零起编，无历史例外表（v1 §5.3 的例外映射随旧仓使命一并终止）。
4. **清单生成与可选核对**（OD-81 ②；本次 K2 演进）：现存清单完备性仍以磁盘发现集合与条目集合对照为准；已退出 HEAD 的历史来源按 §7 显式定位，清单将历史定位声明与现存目录分列，不把历史路径计作现存目录；根 README 与 MECHANISMS 保留整文件生成，人工调用 manifest 时报告遗漏或 freshness 违规。不运行时无检查结论，不自动阻断提交或合并。清单规则仍须遵守，工具形态归 gates 单元。

### 3.3 NFR-09 的仓内形态

新仓无常驻服务器、无数据库：产品、正式状态、决定与共享配置住本仓；完整评审原件住仓外本机耐久归档及备份，过程暂存仍在 ignored 层。新存储及切换条件见 §7.5；旧 Git 历史读取继续按 §7.2 至 §7.4，不作为新轮先入 Git 的要求。

## 4. 顶层目录文法（蓝图）

```text
csthink-harness-plane/
├── AGENTS.md                    # 仓级契约正本（机制区，本地绑定）
├── CLAUDE.md                    # Claude Code 适配指针：指向 AGENTS.md 的薄导入文件（OD-86），非副本（§5.2）
├── README.md                    # 仓库地图 + 概念路由 + 证据布局 + 门命令（机制区，本地绑定）
├── .gitignore                  # 仓级契约（机制区，本地绑定）
├── .agents/                     # 机制区 · 中立能力正本（共享核心，§5.2）
├── .claude/                     # 适配层 · 三区之外的便利层：指向 .agents/ 的发现指针（按需建立，§5.2）
├── mechanisms/                  # 机制区 · 分发载荷本体（§5）
├── apps/                        # 机制区 · 产品代码区：Domain Core / Runtime / standalone CLI 源码（§5.3，载荷贡献之三）
├── sdd/                         # 实例区 · 必需规格链 + 按需 architecture.md（§6.1）
├── tasks/                       # 实例区 · 任务记录目录（§6.2）
├── decisions/                   # 实例区 · 公共技术 Decision（§6.3）
├── changelog/                   # 实例区 · 冻结基线 amendment 记录（§6.3）
├── authority/                   # 实例区 · 重立权威件（按需建立，§6.4）
├── ui/                          # 实例区 · 既有 UI design lineage 与非权威 prototype（§6.5）
├── records/                     # 实例区 · 本仓治理记录（§6.6）
├── reviews/                     # legacy 证据区 · 迁移后退出当前树（§7.5）
├── HANDOFF/                     # 实例区 · 会话交接协议实例（gov-t26 已交付；§6.7）
└── review-attempts/             # 本地暂存，不入 git（§7）
```

三区↔目录对照与分发语义（FR-05 的目录化）：

| 顶层 | 区 | 分发语义 |
|---|---|---|
| `mechanisms/` | 机制区 | **载荷贡献之一 = 本目录整树**（含花名册与模板件；安装语义非复制，FR-02） |
| `.agents/` | 机制区 | **载荷贡献之二 = 本目录整树**（中立能力正本，§5.2） |
| apps 目录 | 机制区 | **载荷贡献之三 = 本目录整树**（cli / Runtime 产品源码与构建面，§5.3） |
| .claude 目录 等 Agent 适配目录 | 非治理便利层（三区之外，§3.2 例外 ②） | 不入载荷本体；下游安装期的适配件生成 / 落位归 gov-t13 / gov-t14 |
| 仓根契约（`AGENTS.md`、`CLAUDE.md`、仓根 README、`.gitignore`） | 机制区（本地绑定形态） | 不逐字分发；其可分发模板形态属 gov-t13 载体设计 |
| `sdd/`、`tasks/`、`decisions/`、`changelog/`、authority 目录、ui 目录、`records/`、`HANDOFF/` | 实例区 | 只参照，**严禁入包**（FR-05：上游治理记录、评审证据与实例内容不得携带入包冒充下游权威） |
| `reviews/`、各任务目录 `reviews/`、`review-attempts/`（本地）、各任务目录 `attempts/`（本地） | 证据区 | 不分发 |

安装包载荷（FR-05）**全部以本仓为源**：机制载荷（`mechanisms/` + `.agents/`）与编排 CLI 与 Runtime 的源码（apps 目录）——源码单仓化系 proposal Amendment 3 / spec-fused Amendment 1 / milestones-fused Amendment 1 同链语义（已生效，2026-08-20，OD-90：三件 Freeze Record 在锁）；载荷组装方式与载体形态属 gov-t13 分发设计。若未来经拓扑 Decision（C-10 选项集）建立独立代码仓，登记于 records/CODE_REPOS.md（按需建立）。三区的语义分类学（复制 / 参照 / 不复制）以 spec-fused FR-05 承接的三区语义为准；本设计承载其在新仓的**物理成员表**。

## 5. 机制区 `mechanisms/`

### 5.1 单元目录文法

```text
mechanisms/
├── MECHANISMS.md                # 单元花名册 + 分发清单（只指路、不复述规则、不承载状态）
└── <unit>/                      # 一单元一目录
    ├── HarnessPlane_<Subject>_Design_v*.md   # 设计正本（如有；命名惯例沿用）
    ├── <可执行物>.py / <配置>.json            # 如有；调用形态保持「python3 <路径> + 退出码」（FR-33）
    └── <素材>                                 # drawio / mmd / 模板件等，如有
```

- 单元目录随其对象被授权起草或重建时建立（just-in-time，不预建）；新单元按本文法成家，**无需修订本设计**。
- 单元的建立、边界与划分粒度以 `milestones-fused.md@r1` 名单和各任务届时的设计为准；本设计只给文法与落点派生规则，不构成任务语义的第二来源。已可示例的居民：`repo-layout/`（本设计定稿产物，随 gov-t1 落位）、各 L0 / L1 机制重建件（gov-t3..t8 等的定稿产物）、模板件与 proposal 引导 skill（gov-t6 交付，属机制载荷——FR-09）。
- `MECHANISMS.md` 花名册受 §3.2 公理 4 约束：保留磁盘发现、整文件生成、只读 freshness 核对与有效负例；人工调用 manifest 时报告违规，不运行时不产生检查结果。

**设计正本的状态不写在正本里。** 设计正本承载设计内容与其依赖声明；对象的治理状态（授权、评审、定稿、修改、终止）一律由 §6.6 的 Owner Decisions 流水日志承载，正本只留一条指针。依据：正本受字节锁，写在其中的状态一旦变化就只能靠 amendment 更新；而上游状态的变化不由本对象触发，会在没有提示的情况下过时。

**设计正本页首恰好两项，顺序固定：**

```text
> Depends on:
> `<裸文件名>`[ <条目 ID 列表>]      # 一行一件；无依赖时单行写 `无`
>
> 权威状态: subject `<单元名>`（治理记录目录按所在仓的布局规则解析；唯一状态正本）
```

- `Depends on` 用**裸文件名**，不写仓内路径——同一份件在本仓与交付仓的路径不同，写死路径最多只能在一个仓里正确；路径由登记表解析，登记表解析不到而文件名在仓内唯一时按文件名解析，多候选报错，而非未显式说明就选择。
- **不写被依赖件的冻结状态**：上游状态由上游自己的治理记录承载，抄进本件即成为一处无人维护、会在没有提示的情况下过时的副本。
- **不写章节号或章节名**：章节号随上游改版重排即失效且不可察；且写单一章节会把依赖面写窄——一份上游权威通常整体约束本件，不止被引的那一节。需要精确定位时写在正文引用处，正文有上下文且受人读核对纪律保护。
- 被依赖件自身带冻结 revision 与条目 ID 的（`spec.md` / `milestones.md` / 公共 Decision），按 `mechanisms/artifact-templates/spec.template.md` 引导块所定的下游引用形态写 `<文件名>@rN <条目 ID>`（原 spec 工件 schema §6.3，该正本已随减重第 5 步退役）。`@rN` 规定的是不可变修订，不属于会过时的状态断言。
- **`权威状态` 指针命名 subject，不写目录路径**——理由与 `Depends on` 同：治理记录目录在本仓与交付仓不同（创始档案库 `docs/governance/<subject>/`，交付仓 `records/governance/<单元名>/`，见 §3.2 公理 3 与 §6.6），写死路径最多只能在一个仓里正确，而设计正本两仓字节相同。命名 subject 后，落点由所在仓自己的布局规则派生，这正是公理 3「登记靠派生、不靠逐处登记发现」的应用。

**正文必备三节**：反思、Rejected alternatives、最低验收场景。其余章节结构不作规定——门设计与流程规则设计的正文形态本就不同，统一规定即为提前抽象。

### 5.2 中立能力正本 `.agents/` 与 Agent 适配层（共享核心 + 产品适配层 + 可执行校验）

```text
.agents/                         # 共享核心：中立能力正本（机制区，随载荷分发）
└── skills/                      # 内置 skills 正本（含 FR-09 proposal 引导 skill，gov-t6 交付；按需建立）

.claude/                         # 适配层示例：Claude Code 的发现面
└── skills                       # 指向 .agents/skills 的指针，不是副本
CLAUDE.md                        # 指向 AGENTS.md 的薄导入文件（OD-86），不是第二套规则
（原生消费 AGENTS.md 与 .agents/ 的 Agent——如 Codex——无需适配件）
```

- **范式（Owner 裁定，OD-82）**：**共享核心 + 产品适配层 + 可执行校验**。规则与能力的正本各只有中立一份——规则正本 = 仓根 `AGENTS.md`，内置能力的调用面正本 = `.agents/`（FR-55）；能力语义与状态推进的正本 = 其调用的机制区可执行物与该单元设计正本（§5.2 Amendment 5）；各家 Agent 的专属目录只做**指向性适配（指针，不是副本）**，不为任何一家 Agent 维护第二套规则或能力。
- 适配层可承载该 Agent 产品专有的发现 / 展示 / 调用形态元数据，但不得承载能力语义或规则实体；移除全部适配件后机制完整可用（FR-55 原样沿用）。
- **可执行校验**：「适配件为指针非副本、正本唯一、指向可解析」属机械核对面（与 §3.2 公理 4 同族；`layout` 门位归 gov-t16，适配指针物理形态裁定归 gov-t14）。
- **指针的物理形态除下一条例外不由本设计裁定**（符号链接 / 薄导入文件 / 安装期生成——gov-t14），且须与治理树符号链接禁令的边界划分对齐：适配层为非治理便利层，其形态不得削弱治理树的位置保证（proposal §5 此前已裁定）。本设计只规定「指向非副本」不变量与 `.agents/` / 适配目录两层落点。
- **例外一件（Owner 裁定，OD-86——r1 R1-B4 整改）**：仓根 `CLAUDE.md` 的物理形态 = **薄导入文件**（内容仅为对 `AGENTS.md` 的单行导入引用，零规则实体；旧仓现行同款、已实证可用），随 gov-t1 建立——使建立时取值固定的状态集合（§8 五件）可施工，不再依赖 gov-t14 定形。.claude 目录 目录与其余适配件照旧归 gov-t14。
- `.agents/` 属机制区、随载荷分发（本仓载荷贡献 = `mechanisms/` + `.agents/` + apps 目录 三个整树，§4 / §5.3）；.claude 目录 等适配目录不入载荷本体，下游安装期的适配件生成 / 落位归 gov-t13 / gov-t14。`.agents/` 内部单元文法（skills 之外将来是否住其他能力类）沿 §5.1 同款 just-in-time 纪律。
- **内置 skill 的目录命名（Amendment 5，Owner 2026-09-03 裁定 D2）**：`.agents/skills/` 下一 skill 一目录，目录名恒为 `cst-<name>`（`cst` 为本产品线内置能力的中立命名空间，`<name>` 取小写短横线短语），各家 Agent 的调用形态（如 `/cst:<name>`）归适配层（gov-t14）。skill 只承载调用形态与引导文字，skill 不自写 Task 状态（FR-31）；能力规则仍归其机制正本。cst-ship 按交接协议 §6.7 指导 Agent 组织已有机制工具、Git 与平台客户端，不要求独立交付执行器；其他 skill 的既有机制调用边界保持。本条自生效起约束新建 skill；**既有 skill 的两面对齐各随其正本的修正程序执行，对齐前维持原状、不构成违规**：目录名一面 = `proposal-guide` → `cst-plan`，需该 skill 自身修订（其正本自减重第 5 步起 = `.agents/skills/proposal-guide/SKILL.md` 自身与 `mechanisms/artifact-templates/proposal.template.md`，proposal-template 设计正本已退役）；承载面一面 = `verify-from-text` 现承载的引导文字与状态推进说明须收回其机制区可执行物与设计正本，需 handoff-protocol 设计 amendment（该 skill 的出处 = handoff-protocol 设计 §10.3）。两项均登记 = 台账 `repo:OD-09`。现存按本命名与本承载面建立的实例 = `cst-review`（评审通道设计 §5.3 调用面的 skill）；首个实例 `cst-freeze` 已随 freeze-record 设计 r6 退役。

### 5.3 产品代码区 apps 目录

- apps 目录 承载编排 CLI 与 Runtime 的产品源码——源码单仓化（proposal Amendment 3 / spec-fused Amendment 1 r2 / milestones-fused Amendment 1 r2，已生效，OD-87/90；交付模型 = 用户经载体安装即用，源码不另设代码仓）。属机制区、随载荷分发（载荷贡献之三）。
- 内部文法（Domain Core / Runtime / standalone CLI 子目录划分、构建与测试布局、技术栈）**不由本设计裁定**——归 M-04 首个代码任务与届时公共 Decision；本设计只规定顶层落点、区归属与一条边界：**代码区治理记录零居留**（不承载任何治理记录、评审证据与任务契约——C-11 同源语义的仓内形态），按需建立（首个代码任务时）。
- apps 目录 不是治理机制单元，不受 §5.1 单元文法与花名册管辖；其身份由根 仓根 README 地图行承载。

## 6. 实例区

### 6.1 规格链与架构说明目录 `sdd/`

```text
sdd/
├── proposal.md                  # 创始三件，以终名落位（gov-t1）
├── spec.md
├── milestones.md
└── architecture.md              # 按需、非冻结工程说明，非规格基线
```

- **落位形态系 Owner 裁定（OD-81 ①）**：创始三件不直接住仓根，由规格驱动开发（SDD，Spec-Driven Development）风格的专用目录管理；目录落名 `sdd/`。
- 收益：① 仓根收敛为纯机制契约面（闭集恒定五件，§8），「升级只替换机制面」（FR-07）在仓根层面零例外；② 规格链三件一目录一眼可及，与业界 SDD 工件目录习惯对齐（SC-3 零上手认知成本低）；③ 「区随目录」公理在仓根之外零例外，三区对齐更彻底。
- **FR-18 同仓语义**：`sdd/` 是产品线仓子目录。正式 feature 的四件来源 = 经 Stage 0 定稿的 `sdd/proposal.md` + 经 Stage 1 冻结的 `sdd/spec.md` + 经 Stage 2 冻结的 `sdd/milestones.md` + 名单唯一命中的任务 ID，全部须在该产品线仓可解析。存量仓的 check/init/fix 接入不要求预先具备这条规格链，但检查或安装成功不等于四件来源已就绪，不授权接纳正式 feature；缺失来源仍按 FR-18 报告。
- **`sdd/` 不是线目录**：单线原则（§3.1）不因此回退——它承载唯一产品线的规格链实例，按内容物类型命名，不区分第二条线。
- `sdd/` 必需成员 = `proposal.md`、`spec.md`、`milestones.md`；唯一可选成员 = `architecture.md`。各成员为普通文件，名称大小写精确匹配；不允许其他文件或子目录。`CODE_REPOS.md` 仍归 `records/`（OD-84，§6.6）。
- `architecture.md` 为按需建立的非冻结工程说明：单向消费 spec 与公共 Decision，说明实际组件/接口、正本指针与真实缺口，不改变产品契约、规范性委托或来源解析，不是 FR-18 的第五件来源。首次独立起草先于状态机/编排施工；check/init/fix 不以其存在为前置，不预建空壳。它不建 Freeze Record，发现上游规则缺口须回其正本处理。

### 6.2 任务记录 `tasks/`

- 位置：`tasks/<task-record-id>/`。计划任务的 `<task-record-id>` 取 `feature-t<N> | design-t<N> | gov-t<N>`，`<N>` 为十进制非负整数且除单个 `0` 外不得有前导零；三族来自冻结 milestones revision 的唯一 task ID，新线自 t0 起编（`milestones-fused.md@r1` §1；与旧线档案同名 ID 不构成同一任务）。runtime hotfix 的 `<task-record-id>` 取 `hotfix-h<64-lowercase-hex>`；它由登记系统首次持久化的 canonical exact bytes 的 SHA-256 派生，**不进入 milestones task-id 文法**。
- Task Definition、按条件建立的非冻结 `design.md`（骨架 = `mechanisms/artifact-templates/design.template.md`，适用与核差 = 交付方法 §6.2）、`rulings/`、`reviews/`、`attempts/` 的内部文法由 `mechanisms/artifact-templates/` 的 `task.template.md` 与 `ruling.template.md`（引导块）承载，legacy alignment 的解析对象 = `records/governance/task-artifact-schema/HarnessPlane_Task_Tree_Alignment_Inventory_v1.json`（只读历史）、解析规则 = `tasks/README.md`（减重第 5 步起；此前由 task-artifact-schema 设计正本管辖，该正本已退役）；gov-t4 只保留四类工件共用的实例首冻定位基准权威。本设计规定 `tasks/` 顶层位置，并与 task 模板共同保持「`attempts/` 永不入 git」的耐久边界（§7）。
- feature、design、governance 与 hotfix 四类 task record 共享同一目录落点；类别差异、source identity、Definition governance、仓内计划任务治理终态与 M-04 runtime state 的分层路由均由 task 模板与 ruling 模板的引导块及 `tasks/README.md` 承载，本设计不建立第二套任务状态或内部文法。

- 台账任务不创建 task record；其变更设计沿用 `records/diagnostics/<主题>/<日期>/` 内的规划材料，按 design 模板核对所需内容，不创建 tasks/repo-od-10/。

### 6.3 `decisions/` 与 `changelog/`

- `decisions/`：公共技术 Decision 落点。Decisions 01–07 的逐条重立件落此（M-04 验收面消费：重立是治理链重建动作、非语义替换，spec-fused §8）；内部文法由 gov-t25 重建的 Decision 机制管辖。
- `changelog/`：冻结基线 amendment 记录落点；内部文法由 L0 重建件（gov-t3 / gov-t25 承载面）管辖。
- 两目录按需建立（首条记录时），本设计只规定落点。

### 6.4 authority 目录（按需建立）

重立权威件的落点。已知首批居民：`MVP_Workflow_v5` 拓扑权威的重立件（proposal §8：整体继承、在新仓按新治理链重立权威）。重立的动作、时点与形态由届时任务承载，本设计不授权。

### 6.5 ui 目录（历史 UI lineage 与非权威 prototype）

UI design lineage 的物理落点（`milestones-fused.md@r1` M-06：lineage 物理落点按新仓布局权威承载——即本节）。上述委托为历史来源。本批 milestones r19 将 M-06 及其任务标 WITHDRAWN，既有 lineage、revision 和 ruling 保留，不能从本节重新授权独立 hp web 或 design 任务。本期产品展示由 Assistant 承接；本节只保留顶层落点和历史解释。

**proposal 阶段的交互 prototype（Amendment 5，Owner 2026-09-03 裁定 D5）**：ui 目录 同时承载 proposal 阶段建立的交互 prototype。它是非权威辅助件：proposal 定稿冻结后经 Owner 授权建立，spec 起草后与之对照核查（贯穿 Stage 0 与 Stage 1），不进入 M-06 的 UI 冻结继承链；由「非权威辅助件、不入 M-06 冻结继承链」推出两条：不作任何任务的上游定位基准、不建 Freeze Record。其可采用自包含单文件 HTML；在 ui 目录 内的子目录与命名由首个实例的授权裁定，不预建空壳。历史 M-06 design-t0 的低保真格式和冻结要求仅用于解释既有证据，不构成本期新的设计或 Freeze 前置；不能因共用格式把 prototype 提升为权威。

### 6.6 治理记录 `records/`

```text
records/
├── CODE_REPOS.md                # 产品代码仓花名册（按需建立：首个代码仓回执时；OD-84 归置，形制以旧 repo-architecture §3.4 为语义参照——一仓一行、只指路不承载状态）
├── history-locations.jsonl      # 历史文件固定来源；按 §7.2 启用后只追加，不承载状态或授权
├── founding/                    # 创始出处清单（gov-t1 交付；SC-1 创始过渡态承载：指向旧仓档案含字节数与 SHA-256 校验值，不搬运本体）
├── governance/<subject>/        # Owner Decisions + Freeze Records（subject 名 = 单元 / 对象名，派生规则 §3.2）
├── diagnostics/<subject>/<YYYY-MM-DD>/   # 日期化诊断快照（按需建立）
└── lineage/<subject>/           # 已过时但需追溯的材料（按需建立）
```

**跨仓固定输入（H-22）**：`records/diagnostics/<subject>/<YYYY-MM-DD>/inputs/<source-repository>/` 可保存为本批核差所需的完整外部输入快照，并以同批 `inputs.json` 列来源仓、原路径、完整提交、bytes 与 SHA-256。副本不独立编辑、不成为本仓的规格或冻结权威；原文相对链接按来源树解释。正式接收由已有 Human/任务记录机制承载，候选归档不等于接收。本修订形成时的联合计划 v0.4 原文固定落在 `records/diagnostics/assistant-hp/2026-09-21/inputs/assistant/docs/design/assistant-hp-joint-implementation-plan.md`，来源提交 `aeae15bdfa66bf747d089ae95c29dda994c66322`，SHA-256 `2b784d88c958c63f19578fac7abea41c22824a8978f4c9055f16e5598d124aad`；同批 README 给出适用性与证据索引。J-01 只有在本布局修订生效且 Assistant 协调者逐字核差接收后成立。root README叙述源、milestones 与任务 HANDOFF 共用该入口。不向 sdd/ 增加成员，不要求新的目录校验器，未来版本用新日期输入清单而不覆盖已接收字节。

内部文法以旧仓现行规则为语义参照。**Freeze Record（定稿记录）的内容形制**——记录行字段、落点与现行冻结事实的解析规则——正本 = `HarnessPlane_Freeze_Record_Design_v1.md`（gov-t5 交付，Amendment 5 起本句自时点句改为指针，Amendment 6 起按其 r6 一行记录形制对齐措辞）；登记机制与锁机制归 `gov-t17`（Amendment 3 自 `gov-t2` 析出），清单核对门归 `gov-t16`。本设计只重定根。**例外一项：`Owner Decisions` 流水日志的条目文法由本设计承载（见本节末）**——承载面是条目外形与卷形制，**外加三处最低承载（`送审授权` 的评审位置取值、`终止授权` 的四项、有 Freeze Record 的对象其 `定稿` 条目的指针形态）**；其余条目的正文内容不作规定。前两处不侵占 `gov-t5`：`gov-t5` 管的是 Freeze Record，而这两类条目的内容形制在冻结名单中无指定归属，其最低承载依据为 `spec-fused.md@r1` FR-27 与冻结方法 §13 两处既有冻结要求的转录；第三处（Amendment 5）只规定条目外形退化为指针，冻结事实的唯一机械正本恒为该次冻结记录行（freeze-record 设计 §3.4）。登记机制（若 `gov-t17` 重建设计采用）：其承载文件落 `records/` 根；**是否存在、文件名与载体格式均由 `gov-t17` 自由裁定**，本设计不预设任何默认形制（r1 R1-B2 整改：撤销原 `registry.json` 具名预留；**归属自 `gov-t2` 改指 `gov-t17` 系随上游 Amendment 3 的析出更正**——登记与锁机制已由该次 amendment 自 `gov-t2` 析出，本更正不改变本设计对该机制的留白范围）。


**Owner Decisions 流水日志的条目文法**（本设计承载；承载面 = 条目外形 + 卷形制 + 三处最低承载，其余正文内容不作规定）：

```text
## <subject 目录名>-D<N> · <类型词>：<标题>（<YYYY-MM-DD>）

<散文>
```

- **ID 前缀 = subject 目录名**，唯一性由目录名在文件系统内的唯一性构造保证，不靠人工扫描避让。既有对象已发出的缩写前缀不倒写；新条目自本文法生效起改用目录名前缀，编号在该对象原有序列上继续递增，不从 1 重起（避免与既有 ID 语义撞车）。
- 编号递增，**发出后永不复用、永不重排**；**只加不删**指原记录事实：既有条目原字节不改写、不从可达 Git 历史删除；整份历史卷退出 HEAD 须另满足 §7；认知变化开新条目并注明取代关系。形制参照本仓 `HANDOFF/LEDGER.md` 文件头的既有纪律。
- `<类型词>` 取九值之一，按两问判定，不靠背表：
  - **问一：该条目让对象往生命周期下一步走了吗？** 走了即**门事件七类**：`起草授权`、`送审授权`、`判词处置`、`定稿`、`施工授权`、`判 done`、`终止授权`。
  - **问二（问一为否时）：它是一个决定吗？** 是即 `裁定`——Owner 对本对象作出的、不推进生命周期的决定（对象选定与次序、通读改稿、standing 授权、暂缓、拒绝、事故处置等）。
  - 否即 `转录`——把既有事实自别处搬入本日志的条目，**不含任何新决定**，须逐项标注来源。
- `送审授权` 条目的评审位置取三值之一：指向本轮评审证据的位置、`Owner 显式跳过`、`未评审`。**`Owner 显式跳过` 是否合法，由冻结方法 §13 评审需求矩阵按对象类判定；本文法只提供承载位置，不授予跳过权。**
- `终止授权` 条目最低承载四项（形制承 `spec-fused.md@r1` FR-27 已冻结的终态记录要求）：停在哪一步、终止理由类别、谁做的决定、此前历史不删除。**终止的后果面**（已冻结件终止后其锁面与目录如何处置、可否重启）**不在本设计范围**，留届时裁定。
- **有冻结记录行的对象（freeze-record 设计 §3.3 三类）其 `定稿` 条目恒为指针形态（Amendment 5，承 Owner 2026-09-03 裁定「Owner Decisions 条目退化为一行指针」；Amendment 6 起按冻结记录行形态对齐）**：正文恰一段，逐项恰为 Owner 指令原话、出口（冻结 / 带保留冻结，带保留时含保留内容与其位置）、该次记录行的指针、非授权一句；re-Freeze、首次 Freeze 与退役三个事件共用同一闭集，条目标题的 `<标题>` 段分别取 `re-Freeze`、`首次 Freeze`、`退役`，不带修订号与对象身份（取值见 freeze-record 设计 §7）。记录行指针的取法 = `records/governance/<subject>/freeze-records.jsonl` + `revision <N>`，不写行号（freeze-record 设计 §7）。条目本身不转录对象身份、前序身份、核差锚或 Changelog 指针（freeze-record 设计 §5.1 所列的记录行字段，其唯一机械正本 = 该记录行，同设计 §3.4；条目内再写一份即第二正本），正文除记录行指针与 Owner 指令原话外，不另写 subject、修订号、日期与该记录的 bytes / SHA-256（判读见 freeze-record 设计 §3.4）。`<subject 目录名>-D<N>` 与 `<YYYY-MM-DD>` 属上列条目外形，不计入正文承载面。锁转换授权句与登记本指向（原 `records/authorizations.jsonl` 与 `records/lock-declarations.jsonl` 的 `authorized_by` / `declared_by`）自 freeze-record 设计 r6 起随两提交仪式与登记本退役、不再在场；前序与新身份由记录行的 `previous[]` 与 `objects[]` 承载，由 Owner 按交接协议 §7 在完整交付指令前或单独人工合并前核差看守。无冻结记录行的对象类（公共 Decision、Task Definition）其 `定稿` 条目不受本条约束。
- **卷形制（Amendment 5，承台账 legacy:KB-47 遗留待裁其一）**：Owner Decisions 一裁一件 - 每条条目独占一个文件 `records/governance/<subject>/HarnessPlane_<Subject>_Owner_Decisions_D<N>.md`（`<Subject>` 派生规则同 freeze-record 设计 §4.1；首卷可为 `HarnessPlane_<Subject>_Owner_Decisions.md` 承载 D1），文件页首以引用块声明 subject、本卷序列号与续编关系；**续编关系按有无前一卷取二值之一**：有前一卷（本卷序列号大于该 subject 的首个条目号）时写前一卷文件名与其条目 ID；无前一卷（首卷，该 subject 的流水自本文件起编，典型为承载 D1 的首卷）时写「流水日志自本文件起编」，不留空、不写 `null`。新卷取当前与 §7 可验证历史文件名中的最大已发序号后续编，不因目录为空从 1 重起；历史前卷的名称与条目 ID 保留，新增续编引用附固定来源 commit 与原路径，原卷不回写。文件入仓后字节不变（不可变历史；原由证据登记覆盖面看守，该看守自减重第 2 步起退役，改由 Owner 按交接协议 §7 在完整交付指令前或单独人工合并前核差承载），流水语义由序列号与续编声明承载而非单文件追加。既有多条目卷是不可变历史，不倒写；既有卷页首自述的「流水日志自本文件起编」自本条起即首卷的合法取值，无须改写。本条把 2026-08-26 起的过渡做法升为规则，legacy:KB-47 其二（列入显式排除）不取。
- 除上述三处最低承载外，条目正文为散文，内容不作规定。

### 6.7 `HANDOFF/`（按需建立）

会话交接协议实例落点；协议由 gov-t26 重建，已建立（正本 = `mechanisms/handoff-protocol/`）。

## 7. 证据区与本地暂存（FR-50 的目录化）

### 7.1 耐久层与历史退出条件

以下是 legacy-git 的留存前提；archive-v1 的新评审原件及已迁移组改按 §7.5。正式决定与其他非评审记录的留存纪律继续成立，不把旧层级措辞应用于新轮。

| 耐久层 | 物理落点 | git |
|---|---|---|
| **入仓永久层** | 初次发布到 `reviews/<subject>/<round>/`（subject 轴）、`tasks/<task-record-id>/reviews/`（任务轴）、`records/`；符合本节的历史文件可按固定 commit + 原路径留存 | 当前受跟踪或经核实可达的 Git 历史原件 |
| **本地暂存层** | `review-attempts/`（subject 级运行时暂存）、`tasks/<task-record-id>/attempts/`（任务级原始材料） | `.gitignore` 排除，永不入 git |

- 关键证据（评审结论、Receipt、内容校验基准、Human 决策）必须处于入仓永久层；本地暂存只承载过程性原始材料（切换前 FR-50 的历史语义）。被审输入内容校验值转录进治理记录并纳入机械核对、暂存证据的晋升规则，由 gov-t9 机制承载；本设计规定的是**耐久层及其可核实的物理来源**，使 FR-37「承重锚只存本地」在结构上无处发生。
- 两轴不合流：subject 轴（数量有限的机制 / 对象类）与任务轴（随任务数线性增长）各自单一规则（语义参照旧 repo-architecture Rejected D，融合线维持）。
- **文档评审与决策面的派生视图（Amendment 5，Owner 2026-09-03 裁定 D4 / A4）**：**决策面** = 从 Markdown 治理件派生、供 Human 在其上作决定的 HTML 视图（Owner 2026-09-03 裁定 D4 命名）；**决策回流契约** = Human 在页面上作出的决定写回仓内治理记录的字段契约（同日裁定 A4）。决策面是派生视图，其生成输出恒落本地暂存层 `review-attempts/<subject>/` 之下，永不入 git；Markdown 恒为唯一权威字节（Owner 2026-09-03 裁定 D4 逐字，台账 `repo:OD-09`；与 `FR-36` 所定「候选到冻结 / 定稿的转换机械可核」相容，但不由该条推出 - `FR-36` 规定的是转换的可核性，不规定 Markdown 与 HTML 之间的权威关系），且 **UI 不创造 authority** - 合法操作集合由 Workflow 状态推导，不由界面元素存在与否决定（NFR-04 逐字转述）。决策回流的结果不落暂存层：按决策回流契约写回入仓永久层的既有治理记录（Owner Decisions 卷、台账），该契约与页面本身的设计归其承载任务（milestones 名单，登记 = 台账 `repo:OD-09`），本条只规定派生视图与正式决定的落点；完整评审原件另按 §7.5。
- `.gitignore` 建立形态须含两条暂存层排除（`review-attempts/`、`tasks/*/attempts/`），随 gov-t1 骨架落地。

历史退出必须逐组列出 source_commit、精确文件集合、内容身份、授权与消费者核验结果，经 Owner 点名批准后才能删除工作树文件并提交。这里只调整 HEAD 留存位置，不改写、重命名或销毁原记录，不把候选冻结、清单建议或工具 PASS 当作删除授权。原 ruling 的个案保留要求优先：gov-t11 的 RU-02-close §三须另获点名处置，旧 ruling 不回写。

必须继续在场：现行机制与产品权威、所有 `freeze-records.jsonl` 的全部记录行（含 retire-only subject）、当前 `check.ref`、Task Definition 与 ruling、公共 Decision、当前 `HANDOFF/progress/`、legacy task alignment inventory、当前 Registry 实际引用的 capability 凭据、活动评审及未完成任务需要的材料。判定依赖具体内容与消费者，不以“目录老旧”替代核验。唯一 candidate baseline 或人工材料只在 ignored 层时，对应组不得退出。

### 7.2 历史定位文件

`records/history-locations.jsonl` 是本仓历史原件的物理定位实例，属证据区。规则与通用读取器住本单元；它不登记治理状态、冻结事实、subject 权威或新的删除授权，不恢复旧登记本。每个获批准退出组追加一行，UTF-8、每行一个 JSON 对象、行末 LF。封闭键集如下：

| 键 | 文法与含义 |
|---|---|
| `version` | 整数 1，布尔值不作为整数 |
| `source_commit` | 完整小写 commit object ID，按本仓 Git object format 的完整长度校验；对象必须是本仓可解析且为 view_commit 祖先的 commit，拒绝 ref 名与缩写 |
| `selection` | 恰含 `roots`、`paths`、`exclude`，各为无重复字符串数组；roots 为以 `/` 结尾的目录路径，paths 为精确文件路径，exclude 为精确文件路径；roots 与 paths 至少一项，排除后非空；只在 source_commit 的树展开，exclude 每项须实际属于展开集合 |
| `paths_sha256` | 展开后去重路径按 UTF-8 字节排序，各附 LF 后连接的 SHA-256，64 位小写十六进制 |
| `objects_sha256` | 同序每项 `path<TAB>blob_oid<LF>` 连接的 SHA-256，同上文法；blob_oid 为该树原对象 ID，不是新造的内容哈希 |
| `authority_ref` | `仓内相对路径#定位符`，恰一个 `#`；定位符为该文件内可唯一精确匹配的条目 ID 或标题全文（不含 Markdown 标题前缀），非空且无控制字符；在该行首次入仓提交的树内能定位到已经在案的逐组授权。行引入提交从路径 Git 历史推导，不写入行自身、不允许未来或自指 SHA |

**文法与来源样例（隔离测试夹具约定，不是本仓退出授权）**：先在夹具仓提交 records/lineage/example/fact.md 内容 `fact` 加 LF，记该 commit 为 S；随后提交授权件 records/governance/example/approval.md，其唯一标题为 `example-D1`，内容明确批准该路径退出，记提交为 A；S 为 A 的祖先。取 source_commit=S 的完整 ID，selection=`{"roots":[],"paths":["records/lineage/example/fact.md"],"exclude":[]}`；paths_sha256 按该路径加 LF 算，objects_sha256 按该路径、TAB、S 树中的真实 blob ID 加 LF 算，authority_ref=records/governance/example/approval.md#example-D1，version=1。在 A 的后继提交追加该行并退出文件，字段全部替换为夹具实值后即合法正例；此例只证明文法及来源，授权真实性仍属人工核差。

| 对上述正例的单点变更 | 拒绝结果 |
|---|---|
| version 改 true、重复 version 键、paths 写 `../fact.md` | `history-invalid` |
| exclude 写未选中的路径，或排除唯一选中路径 | `history-invalid` |
| 任一摘要改一位，或在同一不可变组声称不同 blob | `history-integrity` |
| source_commit 取不存在对象、非祖先或浅历史无法证明的 S | `history-unavailable` |
| 已启用视图删除定位文件，或修改旧行 | 前者缺连续性证据为 `history-unavailable`；证明为删改时为 `history-invalid` |

路径均为区分大小写的相对 POSIX 路径；拒绝绝对路径、反斜杠、空分量、`.`、`..`、控制字符、`.git` 分量及忽略暂存根 `review-attempts/`、`tasks/*/attempts/`。不跟随符号链接或 submodule，仅允许普通 blob mode `100644` / `100755`；不得按路径跨 clone 寻找同名文件。JSON 重复键、未知键、未知版本、坏类型、空行、重复行、非法或无效 selection 均拒绝。roots/paths 重叠只在本行集合内去重，不扩展到新增文件。

行只追加，既有行不可删改或重排。相同 path + blob 的来源重复可去重展示；同一路径的不同 blob 必须保留各自版本且无 source_commit 的读取拒绝歧义，不采用最后一行覆盖。对声称同一不可变退出范围的冲突 blob 判违规；恢复后再次退出必须重新授权、追加新的明确来源，不复用旧组授权。工具只验证授权指针可达与唯一，不判断原话是否足以授权；此项由 Owner 核差。

view_commit 是本次查询的完整 commit ID。首次启用前没有定位文件保持原读取行为；启用后，对历史查询必须通过该路径从首次出现到 view_commit 的 Git 历史核对只追加连续性，丢失、截短、重排、删除后重建或无法证明连续性均拒绝，不能视作空历史。只核定位文件沿革与本次所需组；不要求无关现行操作读取全部历史 blob。浅历史不能证明所需关系时明确未查成。此连续性核验不属于 gates 的工作树语法检查。

### 7.3 共同读取器与错误契约

计划交付 `mechanisms/repo-layout/history_read.py` 与 `history_read_selftest.py`，仅用 Python 标准库；本次设计冻结不包含这些文件的施工。模块提供：

- `list_history(repo_root, view_commit, prefix)`：prefix 为空字符串或合法目录前缀；返回该视图可验证的历史来源列表，按 path、source_commit 的 UTF-8 字节序排序，每项恰含 `source_commit`、`path`、`blob_oid`、`bytes`、`sha256`；同 path + blob 展示一项，选字典序最小来源 commit。须校验涉及组的 selection 与两份摘要。
- `read_history(repo_root, view_commit, path, source_commit=None, expected_sha256=None)`：返回 `content` bytes 及上列元数据。显式 source_commit 的既有证据引用可不依赖定位文件，但仍核祖先、路径、类型和给定哈希；未指定时必须由有效定位文件唯一确定 blob，禁止用最新 Git 日志、裸名或其他 clone 猜来源。哈希在场则必须相等，缺席不代表替代消费者原有哈希校验。
- `validate_locations_syntax(content)`：只做封闭形状、值与路径文法、重复行检查，返回解析对象；不调用 Git，不声称来源完整性，供 gates 共用。

CLI 的命令形态：`python3 -B mechanisms/repo-layout/history_read.py {list|read|check} --repo-root <绝对仓根> --view-commit <完整commit>`。list 可给 `--prefix <目录前缀>`，默认空；read 必须给 `--path <原路径>`，可给 `--source-commit <完整commit>` 与 `--expected-sha256 <64hex>`；check 可给 `--prefix`，默认检查全部组及连续性。各命令拒绝其他命令专属参数和未知参数。list 输出一个 JSON 对象 `{version:1, items:[元数据]}` 到 stdout；check 输出 `{version:1, state:"PASS", groups:<检查组数>, files:<去重文件数>}`；read 的 stdout 仅输出原始 bytes，成功元数据一个 JSON 对象写 stderr。失败时 stdout 为空，stderr 为 `{version:1, code:<错误码>, message:<原因>, path:<相关原路径或null>, source_commit:<相关完整ID或null>}`；必须在输出内容前完成全部相关核验。

退出 0 = 成功；退出 1 = 依赖或内容不可验证，错误码闭集为 `history-not-found`、`history-unavailable`、`history-ambiguous`、`history-invalid`、`history-integrity`；分别对应未命中、对象/祖先/连续性证据缺失、版本歧义、形状/路径/连续性违规、摘要/内容身份不符。退出 2 = 参数错误 `usage-error` 或工具异常 `internal-error`。模块失败抛 `HistoryReadError`，携带同一 code/message/path/source_commit；不得返回空集合代替失败。消费者保留自身退出码与结果 schema，在现有 reason/problems 字段记录来源错误。

Git 使用 argv 参数数组，禁 shell；固定枚举配置，禁 replace objects，发现 graft 拒绝，禁 lazy fetch，不隐式联网、不 fetch、不改 refs/index/工作树/全局配置。commit/tree/selection 验证先于 blob 输出；外部代码、locator、历史正文不执行。仅允许进程内缓存，键含实际 object database、view_commit、source_commit、path；不建后台服务、磁盘缓存或第二套历史目录。

### 7.4 启用、分发与消费者义务

共同冻结只使规则成立，不证明能力已施工。启用历史退出之前须另获施工授权，交付并通过共同读取器及全部受影响消费者的验收；逐组核查活动依赖、固定来源与内容身份、旧 candidate baseline 可恢复性，得到点名退出授权；该组定位行与实际退出文件在同一提交落位。首批检查在临时验证视图完成，source_commit 取删除之前的可达提交；authority_ref 所指授权先在案。可达性与摘要不能由将来尚不存在的提交、自报 HEAD 或整目录当前散列替代。

退出后按相同查询重验，MR/交接含该批真实删除差异与新 H/C；旧 handoff、Receipt、判词、裁定与 inventory 原件不重写。恢复文件的操作仍需其范围授权，不能据此改写来源记录。source_commit 必须保持可达，禁止通过改写历史、清除唯一引用或后续清理销毁这些原件。

启用消费者使用本单元共同读取器，不复制解析实现。分发选择包含这些消费者时必须同时包含共同 helper；仅分发机制代码与设计，不带本仓 history-locations 实例、固定 SHA 或诊断库存。缺 helper 明确失败，不回退为空历史；未启用的老仓仍用原行为。

handoff 按其 §9、评审通道按其 §8.5、Freeze Record 按其 §9 读取，保留各自状态权威。提醒器 `review_evidence` 取现存与历史原轮路径并集，返回原字符串路径列表且不改报告 schema、`non_blocking`、WITHDRAWN 兼容与退出码；依赖读失败映射 `SELF_FAILURE`，不当作零证据。Owner Decisions 新序号按 §6.6 同查历史。

gates 只读取工作树定位声明并调用纯语法校验，不取历史 blob，不因浅克隆否定工作树核对；规则见 gates §4。诊断 `build_page.py` 在生成时读取固定历史原件，维持现有五 tab、自包含离线 HTML；原相对链接及 JSON/图片依赖须嵌入或提供真实固定 commit 读取说明，不能产生伪装仍在场的死链接。不新增服务端、Lavish 操作或产品 UI 机制，视觉验收留在施工批。

### 7.5 本机耐久归档与本批切换（CL-55 候选）

本节与同批 spec FR-50 决定新评审的物理边界。§7.1 中四件先入 Git、关键评审证据必须在场的旧要求仅适用于切换前的 legacy-git 轮；§7.2 至 §7.4 继续管已有 Git 历史读取，不扩展为私人归档索引。新归档协议归评审通道 §8.6，不能用本节替代其发布、继承与失败判断。

| 类别 | 落点与 Git 边界 |
|---|---|
| 产品与正式记录 | 产品正文、代码、测试、Changelog、ruling、Decision、Freeze Record、当前进度继续按既有目录入 Git；只保留该次正式决定所需最终结果、身份及 ArchiveRef |
| 完整评审原件 | 仓外本机耐久归档及备份，独立于任何 checkout；两轴逻辑身份不变，物理目录由通道 §8.6 唯一规定，不入产品 Git |
| 本地暂存 | ignored 的 review-attempts 与 tasks/*/attempts 可作编辑输入和未完成工作区；评审所需原件须归档，未分类或其他任务资料不得批量删除 |
| 已入 Git 的旧评审 | 保留固定 source_commit + 原路径历史；经本节条件迁移并删除当前 reviews 和 tasks/*/reviews，旧引用及原结论保持 |

配置采用 clone 共用的 Git local 配置键 `reviewArchive.repositoryId`、`reviewArchive.primaryRoot`、`reviewArchive.backupRoot`、`reviewArchive.mode`；不使用 worktree 私有覆盖，不自动从 cwd 或 remote URL 改派产品线身份。repositoryId 是安装/迁移时明确绑定的稳定产品线标识，两根保存同值身份文件，跨产品不混用。本仓标识 csthink-harness-plane，主根 <归档主目录>/csthink-harness-plane，备份根 <归档备份目录>/csthink-harness-plane。新 clone 不自动继承本机配置，不能默用 cwd 旁目录。其他产品线在安装配置阶段由 Owner 选择根；产品载荷不硬编码本仓绝对路径。

两根必须是非符号链接的规范绝对目录，互不相等、互不包含，且不位于产品仓任一注册 worktree 内，也不能落在 /tmp 或系统临时目录。检查实际设备/inode，拒绝根别名与硬链接冒充备份；文件副本须不同 inode，逐件字节一致。两处本机目录不等于异机或异盘灾难恢复：允许同一设备，须在备份验证中记录该事实，不声称机器损坏后可恢复。权限按当前用户最小可读写设置；不保存认证秘密，已有输入秘密扫描不放宽。

迁移以显式清单为单位：固定 source_commit、原路径、原 blob/bytes/SHA-256、原轮身份、已识别本地文件和缺失项；同一 source 的逐件身份不得混拼。存量 reviews、tasks/*/reviews 全部成员原样保全，包括缺 Receipt 或超出当前四件形态的旧轮；review-attempts 以及 tasks/*/attempts 中实际请求、投递清单匹配的候选/reference/baseline、原始输出与复审决定一并核查。只存哈希不算快照；历史草稿不能代替原候选。未定位快照按来源缺口记录，允许保存不完整历史，禁止宣称可完整复审。当前活跃轮、唯一仍需输入或被原个案保护的组，条件未满足时保留源。

删除条件全部成立才执行：精确清单及本次授权可核；主副本与独立备份逐件一致；从备份恢复至空隔离目录并校验完整载荷成功；引用、轮号/额度、上一轮继承、当前 Registry、核差、handoff、提醒器、manifest 等实际消费者迁移验证通过；确认没有活动写入；逐件重新比较待删源与保存字节。任一失败不删对应源，报告已完成及未完成范围，不扩大到源父目录。详细库存/每轮迁移结果不入 Git，正式决定只记录批次范围、结果、清单身份与归档引用。

gov-t11 的原 RU-02-close §三保持不可变；本候选提出以后继正式裁定允许其中 task-r1/task-r2 与 changelog-cl-41/r1 的现存原件按本节迁移及退出，CL-41 原候选缺口仍如实保留。该候选不是已生效后继裁定。其他已完成任务 ruling、Definition、冻结行全部行、现行能力配置和当前进度保持在场；旧原件的物理在场要求可由验证过的固定 Git 引用替代，但不得替代原判断。

正式切换决定落 records/governance/review-channel 的下一份 Owner Decisions 卷，属于启用处置，非 Freeze Record 定稿条目；不改变既有定稿卷一段指针文法。该卷正文带唯一 review-archive-switch JSON 块，封闭键为 schema = review-archive-switch/v1、repository_id、mode = archive-v1、implementation_commit、legacy_commit、inventory_ref（ArchiveRef）、authorized_by（本次 Owner 指令定位）。commit 为完整已提交且消费 HEAD 可达的来源；inventory_ref 指仓外 kind=inventory 对象，其中保存精确迁移库存和其逐件身份。引用语法归评审通道 §8.6，配置与正式块必须一致。切换后更换根只核相同 repository_id/原对象，不能选择新空库。

legacy_commit 的树按固定选择规则读取：reviews/ 下全部文件、tasks/ 的直接任务记录子目录下 reviews/ 全部文件，以及 records/diagnostics/review-channel/ 下 Receipt 原件；实际集合以库存校验，缺漏拒绝。该显式来源供共同解析器保持旧路径读兼容，history-locations 的原行不回写，不能给每轮再造一份 Git 索引。当前在场的旧路径仍优先核字节；任一同路径新旧内容冲突拒绝。正式块的模式不可回退到 legacy 写入，旧模式只作历史读取。

启用顺序：共同冻结本批权威；按施工授权交付共享读取/写入器及直接消费者；隔离环境完成通道 §8.6 验收；记录本仓切换决定及实际生效实现 commit，将共用 `reviewArchive.mode` 从 legacy-git 置为 archive-v1；按清单逐组真实迁移与退出。配置中的模式只选择实现，不构成授权，须校验正式切换决定存在且适用于该 clone 的产品线。缺配置的 legacy 模式不能声称满足新轮零入 Git；已宣布启用的仓不能因本机缺配置自动回落旧写入。新 clone 由 Git 内切换决定识别必须配置，原件依赖操作明确拒绝。

施工时 .gitignore 同时排除根 reviews/、tasks/*/reviews/、review-attempts/、tasks/*/attempts/ 和 records/diagnostics/review-channel/ 的完整 Receipt。已有 tracked 原件须真实删除后提交，ignore 不代替迁移；不删除保留的机制代码、测试、模板与正式决定。rules_catalog 仍识别 legacy 根供历史读取及迁移核验，不意味着允许新原件写入。后续受治理 publish 还须按 handoff-protocol 检查全部新增提交；本批起草不改 .gitignore 或本机运行配置。

### 7.6 托管平台首次迁移的历史与材料边界（CL-56）

CL-57 候选（拟 r14，基线 r13）：增加原平台退出后的离线读取与首次 PR 试批配置条件。未冻结或未验收不宣称平台已退出。

托管平台迁移不改变本仓治理历史、archive-v1 原件留存或 task 终态。Git 历史按批准的源 ref/commit 集合逐对象原样转移，目标首次初始化必须走交接协议 §6.6；新增提交中的评审原件禁入仍按 §7.5 和交接协议 §7.1，不以改平台重新创建旧报告提交。

正式计划、当次批准、必要结果沿既有 records/diagnostics/<主题>/<日期>/ 规划材料、records/governance/<subject>/ Owner Decisions 和 HANDOFF/progress/<任务>.md 的各自文法落位，不另建完成状态表。具体迁移的精确 ref/对象清单可作为计划附件，必须固定路径及内容摘要，由批准记录指向已提交的计划身份；仅允许 Git 对象清单和必要的处置摘要，不把完整评审输入或平台秘密写入 Git。完整协作资产导出、含敏感信息的清单与运行原件保存在明确点名的仓外耐久归档及备份，逐件验证并进行恢复，备份失败不得删除源。评审轮的 archive-v1 独立规则继续适用。

独立出生档案库不是本仓 remote 的一部分；本机评审双副本、协作资料、LFS 对象、子模块远端、附件和外部调用方也不由 Git refs 一致推导完成。计划须逐类列出真实存在与处置方式：迁移、保留可查或本次不适用及证据；未查成不能记成没有。旧 GitLab URL 作为历史保留，现行入口只按经核实的新位置提供映射，禁止全仓替换历史。

当实例决定迁移后不再维护源平台时，“保留可查”必须由已验证的离线归档或目标平台满足，不能依赖源 URL 继续在线。独立出生档案库保持独立仓身份及原 commit/path，不混入本仓 main，不改变原治理权威归属；固定其必要 refs、对象及权威路径，保存独立 bundle、逐对象清单和备份，恢复至空目录并核摘要与读取。只将必要的身份、定位和结果写入当前入口，完整导出与含敏感信息的清单留仓外。读取先验证固定 commit/path/摘要，缺失拒绝且不自动 fetch GitLab；不得借离线镜像自称新的治理权威或改写出生记录。当前本仓历史继续使用既有 history_read.py，跨仓调用须显式指定独立恢复仓；不扩本仓 history-locations.jsonl 为跨仓索引。

平台协作资料须保存正文、讨论线程/行内定位、变更版本与 diff、关键身份/时间/关联，以及实际存在的附件、CI trace 等。main 的祖先闭包不能代替关闭未合并 MR 或其他 refs 之外的必要历史，须逐件核差并为决定保留的遗漏对象保存独立可恢复闭包；Owner 明确判定不迁移的测试实现，保存该处置依据与已有必要元数据即可，不把不迁移扩大为删除本机或源端原件的授权。未查成、已过期或服务端不提供的内容逐项列缺失与影响，不以列表空、元数据或本机 commit 存在冒称已备份。最终源 refs、保留分支批准 tip 和目标首次 PR 新增内容须另纳入最终备份及恢复，初次 main bundle 不是最终全量证明。未知未提交材料继续原处保留，归档已提交对象不授权处理它们。

管理类与继承配置用有权限身份只读枚举，只保存必要名称、作用、目标和状态，不保存凭据；对每项明确迁移或停止使用及验证结果。设置变更、关服、删仓和凭据撤销须另有点名授权。退出验收在拒绝访问 GitLab 的环境中核必要权威/历史、评审双副本恢复、目标日常发布和只读接手，并留网络调用证据；缺失资料或读取仍访问源即未完成。备份可恢复与设备容灾分开声明，同设备双副本不能作为设备损毁恢复保证。

初始化 verify 的目标全等只用于首次导入对账；首次 PR 合法增加 refs/推进 main 后，切换核验按 PR 证据、原对象在目标 main 可达和资料恢复，不重做旧初始化全等或删除新内容。首次 PR 的临时 origin/平台配置按交接协议 §6.6 当次试批授权执行，须点名同一 clone 的全部受影响 worktree 和恢复动作；不增加永久双平台入口、不自动完成最终切换。

切换前必须核对全部需保留 refs、C/H 祖先、历史定位与现行冻结对象可读；目标的基本 PR 发布、人工 merge commit、同步和只读接手须按交接协议适用验收完成。源停止日常写入与目标成为唯一入口由当次明确切换指令及结果决定。失败时先保全两端新增内容，再按具体恢复指令处理；不自动删仓、删源、改写历史或关闭其他会话。本条不引入额外的日常交付元数据；日常 skill 组织方式见交接协议 §6.7。

### 7.7 交付清理材料

cst-ship 的清理范围和保留条件归交接协议 §6.7。复用现有任务进度、交接和 Git/平台事实，不新增专用 clone 身份、运行锁或完成登记文件；请求仍在原有合法暂存落点。材料保护依本章既有规则，未获授权或条件未满足的目录与引用保留。

## 8. 允许成员固定的仓根名单与事实正本对照

- **当前允许的仓根文件集合（本次候选）**：`AGENTS.md`、`CLAUDE.md`、仓根 README、`.gitignore`，外加顶层目录。仓根实例零居留（规格链住 `sdd/`，OD-81 ①）。`.gitlab-ci.yml` 属 gov-t1 建立时的历史成员，本次候选退出闭集。
- **按需建立成员（建立事件明确固定）**：gov-t14 定形的**其余**适配件（该设计冻结后经本设计 amendment 入集）——`CLAUDE.md` 不在此列，其形态已由 OD-86 裁定为薄导入文件、随 gov-t1 建立（§5.2 例外条）。`CODE_REPOS.md` 住 `records/`（§6.6，OD-84），不是根成员。
- 仓根其余任何新增受跟踪文件均须回本设计显式 amendment；「仓根受跟踪文件 ⊆ 闭集」机械可核。
- 根 仓根 README 职责：仓库地图（顶层目录一句话语义 + 三区对照）、概念路由、证据布局与 subject 花名册、门命令。纪律：只指路、不复述规则；与权威正本冲突时以后者为准；其清单类内容受 §3.2 公理 4 核对。

**「一类事实一个正本」对照（OD-81 ③）**——每类工程事实恰有一个正本位置，他处只引用不复述，防第二正本漂移：

| 事实类别 | 唯一正本 |
|---|---|
| 仓级协作规则 | `AGENTS.md`（`CLAUDE.md` 等适配件只指向，FR-55） |
| 内置能力（skills）的调用面 | `.agents/`（`.claude/skills` 等适配件只指向，§5.2） |
| 内置能力的语义与状态推进 | 能力规则归机制正本；Task 状态写者保持 spec FR-31。cst-ship 的 Agent 组织例外见 §5.2，其余沿既有机制可执行物承载 |
| 机制的设计语义、舍弃项与残留 | `mechanisms/<unit>/` 设计正本 |
| 一次冻结事件的冻结事实（对象身份、前序身份、Changelog 指针、核差锚、Owner 决定三项的转录） | 该次冻结记录行（freeze-record 设计 §3.4 / §5.1；`定稿` 条目与 Changelog 只引用不转录，§6.6） |
| Owner 冻结决定（指令原话、出口、保留内容） | 该次 `定稿` 条目（§6.6；冻结记录行的 `instruction` / `exit` / `reservation` 转录之，freeze-record 设计 §3.4） |
| 单元花名册与分发清单 | `mechanisms/MECHANISMS.md`（受公理 4 核对） |
| 产品定义与计划（规格链） | `sdd/proposal.md`、`sdd/spec.md`、`sdd/milestones.md` |
| 产品级工程说明（非冻结、非规范性权威） | 按需 sdd/architecture.md，正本规则仍回 spec / 公共 Decision |
| 跨任务公共技术裁定 | `decisions/` |
| 对象（subject 级定稿对象）的当前治理状态 | `records/` 治理记录（冻结件状态头只是被审快照） |
| Task Definition governance | `tasks/<task-record-id>/rulings/` 与按 §7.5 定位的原件；candidate / finalized / redefinition 按 `tasks/README.md` 生命周期三句与 latest applicable ruling 解析（原 task schema 的 latest applicable event），Definition 页首不承载状态 |
| 本仓计划任务治理终态 | latest applicable ruling 的 header `Type: done` 与 Owner Decision；contract、HANDOFF、commit 与 filename slug 均不构成 done 正本 |
| 产品 Workflow runtime state | M-04 单一写者的 durable state / event store；Task record 只承载 Human rulings 与 review evidence，不成为第二 runtime state store |
| 评审过程证据 | §7.5 本机耐久归档；旧 reviews 与 tasks/*/reviews 只按 legacy 来源读取 |
| 地图、路由与命令入口 | 根 仓根 README（只指路） |
| 开放项与教训台账 | `HANDOFF/`（gov-t26 协议已重建） |

### 8.1 领域状态与物理观察（H-12/H-13）

领域 durable state 保留 `refs/harness/runtime`；Git common-dir 下 `harness/writer.lock`、bootstrap 与 binding 由两入口共用，只有当前控制代次的 Domain Core 提交正式领域结果。锁是合作入口协议，不阻止同账户外部程序直接修改，发现外部漂移固定事实并停报。

`<git-common-dir>/harness/executions/<executionRequestId>/` 是物理执行观察目录，监督程序对每请求唯一追加；hp 与 standalone/embedded 两入口协调器只读。记录携带 Contract ExecutionRecord 的请求、监督身份、boot/PID/启动时间、放行与退出事实，执行写者不持有领域控制权。目录不入产品Git，不成为领域状态库；无目录、损坏或身份不符不证明未启动，也不能通过更换请求ID跳过保护。相关领域证据引用按摘要固定；导出/保留/恢复必须同时保全仍被引用的物理原件，备份失败不删除。旧Host消失、旧代次、PID复用、逃逸后代或观察不全时保护资源，待同一执行事实核清后才按领域规则结算。不得以关闭领域任务替代物理退出证据。

## 9. 与下游产品线仓骨架的关系

- 本布局的**实例区 + 证据区文法**是下游产品线仓骨架的蓝本（FR-05、FR-06、SC-3、SC-9），不是对所有存量仓实施目录重排或创始实例落位的指令。新建仓可按蓝本获得规格链模板与记录落点；存量仓先检查并由 Owner 核对接入候选，保留已有源码、历史、指令及构建/测试/CI 配置，同名冲突与未知归属不得覆盖。
- `sdd/` 必需规格链、按需架构说明与任务、Decision、治理记录、评审证据及本地暂存的约定按安装清单和实际事件按需使用。空规格基线允许 check/init/fix 接入；check 只读且不创建骨架，init 不把模板或既有文档冒充已冻结实例，fix 仅修改本产品拥有的安装与接入产物。正式 feature 仍经 §6.1 的来源核验；现有事实可经授权起草为候选，再走 Stage 0/1/2，不回填或伪造本仓创始历史。
- 机制区源树（`mechanisms/`、`.agents/` 与 apps 目录）**是本仓自身使用的源树形态**（机制与产品的源之家；proposal §6 自举原则）：下游仓获得的是安装形态（FR-02 安装语义非复制，可自报版本、可升级；Owner 交付模型意向 = npm 式安装即用，gov-t13 / feature-t8 强输入），其物理形态由 gov-t13 载体设计裁定，本设计不预判。
- 下游骨架不携带本仓 `records/`、`reviews/`、任何实例内容（FR-05 禁令）；骨架的精确内容清单属 gov-t13 / feature-t8 交付面（FR-06 成文交付清单）。
- **公开交付面约束（Owner 意向在案，OD-83）**：实例区与证据区**永不进入任何公开交付面**，公开面以机制区三树为界；仓库可见性与公开交付面解耦——本仓（正本）可长期保持私有，公开形态意向为「同名公开仓承载机制区的只读单向投影 + 载体安装包」，其定形（导出机制、投影仓根件、引用可解析性检查的适用面、proposal §5 把措辞改写为唯一含义）归 gov-t13 分发设计。投影仓不是正本、不承载治理记录，反向修改不被接受（O-11 下游反馈经 Human 中转语义同构）。

## 10. 创始落位次序与授权门

```text
本设计起草（本次，OD-80）→ Owner 检查 → 授权送审（旧仓通道；repo-layout subject 标准登记随送审授权执行）
→ finding 处置 → Owner Freeze（gov-t0 完成面；定稿形态比照标准链）
→ gov-t1 新仓骨架落地与创始实例落位（独立任务、独立授权；本设计定稿产物随之落位 mechanisms/repo-layout/）
→ gov-t2 门重建接线（创始阶段历史；本次候选的 layout / manifest 改为人工可选核对）
```

- 每步授权独立，前一步完成不自动授权后一步（继承冻结方法纪律）。
- 本设计冻结**不授权任何新仓创建动作**：新仓现状 = Owner 首个 commit `44200dd`（仅 `.gitignore`），一切创始内容动作属 gov-t1 届时的单独授权。

## 11. Minimum acceptance scenarios

### S1 · 载荷贡献按目录取整

```text
Given  gov-t13 分发设计需要本仓的载荷边界
When   按本布局取件
Then   本仓贡献 = 机制区三个整树（mechanisms/ 含花名册与模板件、.agents/ 含能力正本、apps/ 含 Domain Core、Runtime 与 standalone CLI 源码），无逐文件枚举
And    实例区、证据区与适配目录无一文件入包
```

### S2 · 新增一道门一处成家

```text
Given  某个新机制对象被授权起草或重建
When   其设计与实现落地
Then   mechanisms/<new-unit>/ 建立并承载设计、实现与测试用例
And    records/governance/<new-unit>/ 随冻结建立；评审逻辑身份按名字派生，切换后不创建仓内 reviews/<new-unit>/
And    花名册与路由由保留的生成链更新，治理事件按对应记录协议落位；不要求新增 CI 行
```

### S3 · 创始三件同仓、四件来源可解析

```text
Given  gov-t1 完成创始实例落位
When   任一 feature 任务做来源核验（FR-18）
Then   sdd/proposal.md、sdd/spec.md、sdd/milestones.md 同仓在位
And    milestones 名单唯一命中的任务 ID 构成第四件，四件全部在本仓可解析
And    architecture.md 缺席或在场均不改变正式来源组成；其他文件、错误大小写或子目录仍违规
```

### S4 · 任意任务一处看全

```text
Given  某任务走完其生命周期
When   查看 tasks/<task-record-id>/
Then   契约与裁定仍在该目录内受 git 跟踪，评审结论与 manifest 初次发布受跟踪，历史退出后由 §7 固定来源验证并读取
And    attempts/ 原始材料未进入 git
```

### S5 · 本地暂存全丢不失去定位基准

```text
Given  review-attempts/ 与全部 tasks/*/attempts/ 因磁盘故障丢失
When   审计任一次已完成评审「评审方当时看到了什么、结论是什么」
Then   评审结论、回执与内容校验值记录在入仓永久层可核（FR-50）
And    丢失只波及过程性原始材料
```

### S6 · 单线无第二套线目录

```text
Given  新仓任意时点
When   列出顶层目录
Then   不存在 gov/、product/ 或任何线目录
And    gov-t<N> 只作为 tasks/ 下的任务目录出现
```

### S7 · 仓根纯净可机械核

```text
Given  人工核对仓根布局
When   运行 layout 检查仓根受跟踪文件
Then   恰为 §8 闭集之内（含已建立的按需成员），无任何计划外文件
```

### S8 · 下游骨架无上游权威事实

```text
Given  下游团队选择新建仓或保有实际代码与历史的存量仓接入
When   检查接入候选与安装后的内容
Then   不含本仓 records/、reviews/ 或实例区的任何内容
And    已有源码、历史、指令及构建/测试/CI 配置受保护，冲突和未知归属不覆盖
And    空规格基线可接入，但安装成功不构成正式 feature 四件来源就绪
And    模板与既有文档不被自动声明为已冻结，下游治理产物仍为该下游资产
```

### S9 · 适配件是指针不是副本

```text
Given  Claude Code 与 Codex 同时接入本仓
When   核对规则与能力的正本
Then   规则正本唯一（AGENTS.md），CLAUDE.md 仅为指向它的适配指针
And    能力正本唯一（.agents/skills），.claude/skills 仅为指向它的适配指针
And    「副本型适配件」可被机械校验亮红（§5.2 可执行校验）
And    移除全部适配件后机制完整可用
```

### S10 · 公开投影面不含治理内容

```text
Given  gov-t13 定形的公开投影仓随某次发版更新
When   检查其全部内容与全部历史
Then   内容恰为机制区三树（mechanisms/ + .agents/ + apps/）的发版快照与自带根件
And    sdd/、tasks/、records/、reviews/ 的任何内容与任何历史 commit 均不出现
And    投影仓内无声称权威的治理记录（正本唯一在上游私有仓）
```

### S11 · hotfix task record 不进入 milestones

```text
Given  产品内一次 hotfix 登记已成功持久化 canonical exact bytes
When   为该登记建立 task record
Then   目录名匹配 hotfix-h<64-lowercase-hex>，digest 由该 canonical exact bytes 的 SHA-256 唯一派生
And    该 record 住 tasks/<task-record-id>/ 并服从 task 模板（mechanisms/artifact-templates/task.template.md）
And    milestones task-id 集合不因此增加任何 hotfix 条目
```

### S12 · 内置 skill 的命名与承载面（Amendment 5）

```text
Given  一个新机制单元交付一件可执行物，并要为它建立内置 skill
When   按 §5.2 落位
Then   目录名为 .agents/skills/cst-<name>，非 cst- 前缀即违反本文法
And    该 SKILL.md 只承载调用形态与引导文字，能力语义与状态推进在机制区可执行物与该单元设计正本
And    既有 proposal-guide 与 verify-from-text 在各自正本的修正程序执行前维持原状，不判违规
```

### S13 · 定稿条目是指针、卷是一裁一件（Amendment 5）

```text
Given  某有 Freeze Record 的对象经 Owner re-Freeze
When   按 §6.6 建立 定稿 条目
Then   条目正文恰一段，只承载指令原话、出口（带保留时含保留内容与其位置）、记录行指针与非授权一句
And    正文除记录行指针与指令原话外不另写对象身份、前序身份、核差锚、subject、修订号、日期与该记录的 bytes / SHA-256（唯一机械正本 = 该冻结记录行）
And    条目标题的 <标题> 段不带修订号与对象身份
And    该条目独占一个 HarnessPlane_<Subject>_Owner_Decisions_D<N>.md 文件，页首声明 subject、本卷序列号与续编关系（前一卷文件名与其条目 ID）
And    既有多条目卷不倒写
```

```text
Given  某 subject 此前没有任何 Owner Decisions 卷，Owner 对其首个冻结件作出首次 Freeze 裁定
When   按 §6.6 建立承载 D1 的首卷
Then   页首引用块声明 subject 与本卷序列号，续编关系写 流水日志自本文件起编（无前一卷可指，不留空、不写 null）
And    条目正文恰一段，只承载指令原话、出口（带保留时含保留内容与其位置）、记录行指针与非授权一句
And    正文的排除项与标题文法同上一场景，首冻的标题段取 首次 Freeze
And    该 subject 的下一卷续本卷，写本卷文件名与 D1
And    两个方向的正文均以非授权句收尾，均不含锁转换授权句（该句自 freeze-record 设计 r6 起退役）
```

### S14 · ui 目录 内的 prototype 不是权威（Amendment 5）

```text
Given  proposal 定稿冻结后经 Owner 授权在 ui/ 建立交互 prototype
When   spec 起草并与之对照核查
Then   prototype 不进入 M-06 的 UI 冻结继承链
And    没有任务以它为上游定位基准，也不为它建立 Freeze Record
And    冻结继承链上的对象集合不因该 prototype 增加任何成员
And    prototype 与 design-t0 均可用自包含 HTML，后者仍经独立视觉评审与 Human Freeze
```

### S15 · 决策面派生视图落暂存层（Amendment 5）

```text
Given  从某治理件生成 HTML 决策面供 Human 作决定
When   核对生成输出的落点
Then   输出全部在 review-attempts/<subject>/ 之下，git 不跟踪任何一件
And    Markdown 治理件字节不因页面生成而改变（唯一权威字节）
And    Human 在页面上作出的决定按决策回流契约写回入仓永久层的既有治理记录，不停留在暂存层
```

### S16 · 历史定位与完整性

完整来源的 list/read/check 成功；重复键、坏 selection、摘要失配、同名不同版本、缺 blob、浅历史、启用后定位文件丢失/截短分别按 §7.3 拒绝；未启用仓保持原行为。显式 source_commit 可读旧引用但仍拒绝非祖先、链接、越界路径与错误哈希。验证无 fetch、无工作树副产物。

### S17 · 跨消费者与退出切换

分两批退出包含旧登记本与评审轮的隔离样本；第二批仍能申报旧冻结状态、保持轮序/额度/继承、Owner Decisions 序号不重起；缺 helper 与来源缺失明确失败。现行 check.ref、所有 JSONL 行、活动凭据和 gov-t11 个案均不得被通用规则移除。分发不带本仓实例，页面离线链接可用。此处只规定施工验收，本次起草未运行。

## 12. Rejected alternatives

### A. 创始三件直接住仓根（本稿初版具体做法）

否决（Owner 通读裁定，OD-81 ①）。仓根混住实例使允许成员固定的仓根名单随实例演进膨胀、机制与实例两区在根层混排；收敛为纯机制契约面后，根成员以 §8 允许集合为准、可机械核对，「升级只替换机制面」（FR-07）在根层零例外。规格链改由 `sdd/` 目录管理（§6.1）。

### B. 以 `product/` 线目录承载实例（v1 方案的延续）

否决。线目录的区分对象是第二条线；单线前提下它不再区分任何东西。`sdd/` 按内容物类型（规格链工件）命名，不按线身份命名，与单线原则（§3.1）不冲突。

### C. 沿用 v1 的旧仓迁移蓝图使命

否决。OD-55/56 终裁旧仓整体转档案、新仓治理链从零重建；迁移对照表与跨区内容校验值解析（v1 §10/§11.3）的服务对象已不存在。旧仓维持原样即是其档案职责。

### D. 可执行物集中一个 `scripts/`

否决（承 v1 Rejected C）。单元身份分居两地，「新增一道门 = 加一个目录」不成立；集中入口的便利由花名册与根 README 的门命令行承载。Agent 中立不受影响：调用形态仍是「python3 + 路径 + 退出码」。

### E. 治理记录并入各单元目录（`mechanisms/<unit>/records/`）

否决（承 v1 Rejected D）。分发载荷将携带本仓本地权威事实，直接违反 FR-05 禁令。

### F. 证据区并入 `records/`

否决（承 v1 Rejected E）。权威事实（裁定与冻结）与过程证据（评审结论与回执）是两类消费语义；合置即恢复旧仓 `docs/` 三区俱全的问题。

### G. 下游骨架携带 `mechanisms/` 源树

否决。源树复制回到「复制」老路：版本自报（FR-02）、升级只替换机制面（FR-07）、卸载边界（FR-08）全部无从机械成立。下游获得安装形态，形态由 gov-t13 裁定。

### H. 预建全部单元与按需目录

否决。just-in-time 建立继承方法 §9 反过早抽象纪律；空目录 git 不跟踪，预建只能靠占位文件制造噪音。

### I. 引入 .agents/notes 决策记忆层

否决（起草侧具体做法，随 OD-82 范式评估）。「为什么这样做」的正本在本仓已有落点：跨任务技术裁定 = `decisions/`，权威裁定与冻结事实 = `records/`，设计理由与舍弃项 = 各设计正本的 Rejected / 反思节（§8 对照表）。再引一层决策笔记即第二正本漂移源，与「一类事实一个正本」冲突。

### J. Owner Decisions 卷列入证据登记的显式排除（Amendment 5，台账 legacy:KB-47 其二）

否决。KB-47 曾备两案：其一把「一裁一件」升为规则（本次 §6.6 采纳），其二把 Owner Decisions 卷列入证据登记覆盖面的显式排除项，使单文件可继续追加条目。取其二即为流水日志一类开一个字节不可变性的缺口，而该不可变性正是「条目入仓即定、不倒写」的物理承载（gates locks 设计 §9.6.2 覆盖面）；排除一旦成立，卷内既有条目可被无痕改写，其看守只剩人核。其一零豁免达成同一流水语义（序列号 + 续编声明），故不取其二。

## 13. 与既有冻结决定与旧稿的关系

| 既有决定 / 材料 | 关系 |
|---|---|
| 旧稿 v1（未冻结草稿） | **被本稿就地取代**（OD-80 ③ 显式授权覆盖；旧稿由 git 历史承载）。其三公理与单元文法经融合前提检验后继承；旧仓迁移使命终止 |
| OD-51 / OD-52 / OD-53（旧仓布局系列终裁） | 其对象是旧仓改造，随 OD-55/56 融合终裁收束为档案语境；本稿不再承载、不倒写 |
| OD-54（治理线四件形制，原 open） | 已被融合终裁取消（治理线实例四件不复活，OD-55 系列）；v1 的 `gov/` 落点预留随之失效 |
| repo-architecture（OWNER FREEZE） | 管辖旧仓照旧不动。其三区语义、任务目录文法经 spec-fused FR-05 / C-11 以产品需求形态承接进融合线；其两仓边界语义经 C-10 改写为拓扑选项集（amendment 链），本设计按需求落点化；不改旧件正文 |
| proposal Amendment 3 / spec-fused Amendment 1 / milestones-fused Amendment 1（源码单仓化，**已生效** 2026-08-20，OD-87/90） | 本候选 §4 / §5.3 代码区语义的上游前提——已生效（Freeze Records：proposal `_r4`、spec-fused `_r2`、milestones-fused `_r2` 在锁），r2 送审前置满足 |
| 旧七份 Layer 2 冻结设计（schema 与机制） | 管辖对象是旧线实例与旧仓机制；新仓对应机制由 gov-t2..t8 重建，本设计只给其单元落点 |
| spec-fused 页首布局边界声明 | 该声明所称「布局设计（待出生权威）」即本件；自本设计冻结起物理落点由本设计回答 |
| 冻结方法（FINAL FREEZE） | 过程规则不动；本设计按 §13「Layer 2 reference design」行走 required 评审 + Owner Freeze。方法自身的新仓重建属 gov-t3，与本设计无正文交叉 |
| `MVP_Workflow_v5` 拓扑与产品语义 | 不触碰。本设计是纯落点设计，不新增、不移除任何过程 Gate 或产品语义 |

## 14. 作者侧一致性自检

- 与 `milestones-fused.md@r1` 一致：gov-t0 条目五项边界逐项有承载——机制单元文法（§5）、分区对齐（§4）、允许成员固定的仓根名单（§8）、证据耐久分层落点（§7）、载荷目录边界（§4/§9）；§1 过渡执行条款照引；未复述 §3 排序语义（单一来源纪律），后续任务仅以「独立授权」引出。
- 与 `spec-fused.md@r1` 一致：FR-05 → §4/§9 + S1/S8；FR-50 → §7 + S5；NFR-09 → §3.3；FR-18 → §6.1 + S3；FR-55 → §5.2（只规定正本住机制区，不裁物理形态）；FR-33 调用形态原样沿用；未把 spec 挂给其他任务的需求吸收为本设计义务。
- 与 `proposal.md`（FINALIZED + A1/A2/A3）一致：自举原则 → §9 源树声明；指向性适配件范式经 OD-82 落为 §5.2 两层落点与指针不变量，物理形态仍不展开（gov-t14）；代码仓拓扑选项集与本线仓内代码区终裁（A3 §4 旅程句）→ §4 载荷分工、§5.3 apps 目录 代码区与 `CODE_REPOS.md` 按需建立。
- 与 OD-55/56 一致：零迁移、旧权威不搬运、新线自 t0 起编、创始出处清单形态（§6.6 `founding/`）。
- 与 OD-81 一致：三项裁定逐一落实——规格链 `sdd/` 落位（§6.1 + S3）、清单机械核对公理（§3.2 公理 4 + §5.1）、事实正本对照（§8）。触发材料属仓外调研，本设计正文不引为依据，仅以仓内在案先例与 Owner 裁定为据。
- 与 OD-82 一致：共享核心 + 产品适配层 + 可执行校验范式落实（§5.2 + §4 载荷面 + S9）；指针物理形态不代裁（gov-t14；`CLAUDE.md` 一件系 Owner OD-86 显式缩小范围），符号链接禁令边界照 proposal §5 此前已裁定转述。
- 与 OD-83 / OD-84 一致：公开面边界不变量入 §9 + S10（定形留 gov-t13，不代裁）；目录名保持 `sdd/`、`CODE_REPOS.md` 归 `records/`（§6.1 / §6.6）。
- 与 OD-86 / OD-87 一致：r1 四条 blocking 逐条整改在稿（B1 → §4 / §5.3 代码区〔以 amendment 链生效为送审前置〕；B2 → §2 / §6.6 / §15 登记机制降区域级；B3 → §3.3 / §8 对象状态与任务状态拆分留白；B4 → §5.2 例外条 / §8）；apps 目录 语义与 amendment 链候选文本逐字对齐，不超前、不复述其正文。
- 本次改稿未创建新仓内容、未登记评审 subject、未修改任何既有冻结件；旧稿覆盖有 OD-80 ③ 授权。
- Sources 逐件实读核对（2026-08-20 本会话），无凭记忆引用项。

该检查是作者侧声明，不构成跨模型提供方 Reviewer 的 Verdict。

## 15. 反思

### 必须现在定（本设计承载）

- **顶层文法与三区对齐**——gov-t1 骨架落地的直接输入；晚定则骨架无权威，落一件错一件；
- **规格链目录与仓根纯净闭集**——gov-t1 创始落位与 FR-18 四件解析的物理前提（OD-81 ① 落实）；
- **共享核心与适配层两层落点**——`.agents/` 内置能力调用面正本 + 指针型适配（OD-82 落实）；不定则各家 Agent 各长一套能力副本，Agent 中立（FR-55 / NFR-07）失去物理承载；
- **产品代码区落点**——npm 式单源仓交付模型的物理承载（OD-87 链）；不定则 M-04 的代码交付无落点、载荷贡献面不完整；
- **载荷目录边界**——gov-t13 分发设计的准绳（FR-05 落点化），不定则打包回到逐文件枚举；
- **证据分层落点** - gov-t9 耐久归档与 Git 排除规则的前提；按 §7.5 区分正式记录、归档副本与暂存，唯一快照不得只在可清理目录。
- **条目文法的两项补齐与 skill 落位面（Amendment 5）** - `定稿` 条目的指针形态与卷形制（一裁一件）是 freeze-record 设计「唯一机械记录」在条目侧的物理前提，不定则冻结事实继续三处并记且无准绳；`cst-*` 命名与「skill 只承载调用面」不定则每件内置能力落位无规则可依、能力语义可在 skill 内长出第二份正本。

### 同类潜在 bug 一并防止

- 新对象「想到一个地方放一下」（§5.1 单元文法 + S2 防止）；
- 实例或证据混入分发载荷（§4 三区对照 + S1/S8 防止）；
- 关键证据滞留本地暂存（§7.5 原件保全与备份恢复验收防止）；
- 第二套线目录借旧惯性复活（§3.1 单线原则 + S6 防止）；
- 仓根实例文件发胖（§8 闭集 + S7 防止）；
- 清单漂移：§3.2 公理 4 与 §5.1 保留生成与核对能力；人工运行 manifest 时可报告遗漏或 freshness 违规，未运行不会自动发现或阻断。
- Agent 专属目录长出第二份规则或能力正本（§5.2 指针不变量 + 可执行校验 + S9 防止）；
- 治理内容或治理历史随公开面泄漏（§9 公开面约束 + S10 防止）；
- 治理记录、评审证据渗入代码区（§5.3 零居留边界防止——C-11 同源语义的仓内形态）。

### v1 可接受残留（分级）

- **历史 P1**：gov-t1 至 gov-t2 的创始窗口曾靠人工核对，后由 M-01 原接线验收收口。CL-47 候选使 layout / manifest 再次成为人工可选工具，未运行时不存在机械覆盖；不得沿用创始接线事实声称当前提交必受检查。
- **接受**：单元划分粒度由各重建任务裁定；四类工件的共用首冻定位基准与各自物理 schema 已分别由 gov-t4、gov-t19、gov-t20、gov-t21、gov-t22 定形；四份 schema 设计正本已随减重第 5 步退役并合并为 `mechanisms/artifact-templates/` 模板集单元，按 §5.1 文法成家、本设计零单元边界改动。后续若需调整单元边界，回本设计小 amendment。
- **接受**：登记机制只规定区域级落点（`records/` 根）；其存在与形制由 gov-t17 裁定、无需回本设计 amendment（选择 `records/` 之外的落点才需要）。
- **接受**：ui 目录、authority 目录、`HANDOFF/` 等按需目录的内部文法待各自机制重建（落点先规定、文法后到）。
- **接受**：下游骨架的精确内容清单属 gov-t13 / feature-t8（FR-06），本设计只给蓝本关系声明。
- **接受**：`sdd/` 命名取业界规格驱动开发（Spec-Driven Development）惯称，非仓内既有术语；其语义由本设计与根 README 路由承载。
- **接受**：适配指针的物理形态与符号链接禁令的边界划分归 gov-t14（`CLAUDE.md` 一件已由 OD-86 提前裁定为薄导入文件——Owner 对该留白的显式缩小范围，非 gov-t14 越权）；若届时证明某家 Agent 的指针形态不可行（必须实体文件），该例外须回本设计 amendment 显式记录，不得未显式记录就落副本。
- **接受**：公开投影的定形（导出机制、投影仓根件与责任声明、FR-03 检查对投影面的适用、机制正本内治理引用的处置、proposal §5 把措辞改写为唯一含义）归 gov-t13（OD-83 open 已登记）；本设计只规定「实例区与证据区永不进入任何公开交付面」的边界不变量。
- **已解除（原 P1）· 送审前置依赖 amendment 链**：§4 / §5.3 的代码区语义曾以三件 amendment 生效为前提（OD-87）；该链已于 2026-08-20 生效（r5 `FAIL` 一处整改 → r6 `PASS` 零 findings → 三件 re-finalization / re-Freeze，OD-89/90），前提满足，残留解除。
- **接受**：apps 目录 内部文法与技术栈留 M-04 首个代码任务与届时公共 Decision；本设计只规定顶层落点、区归属与治理记录零居留边界。
- **未决横切，不由本设计裁**：适配指针物理形态（gov-t14——本布局 §5.2 只规定落点与不变量）、分发载体（gov-t13）、apps 目录 内部文法与技术栈（M-04 与届时 Decision——本布局 §5.3 只规定落点与零居留边界）、TUI（OD-77，M-04 设计时评估）——各留待其届时设计。

- **接受**：本次新增的页首文法与流水日志条目文法**没有逐字段的机械门看守**。**须与既有覆盖面区分**：现行冻结契约门**确实**机械核对本设计的字节锁与 review lineage（依据本对象 Freeze Record §6：其 §1 / §2 内容校验值自入库起受 `scripts/check_frozen_contracts.py` 核对）；该门**不做**的是按字段校验设计正本的页首与日志条目文法——其逐字段状态头校验面只覆盖 Layer 3 五类实例（`spec.md` / `milestones.md` / 公共 Decision / Changelog / 任务契约）。合规靠评审与人核；文法的机械化归 L1 门的重建任务。
- **接受**：`Depends on` 的裸文件名解析依赖「被依赖件的文件名在仓内唯一」。该前提现下成立——本件页首所列**八件依赖已逐件实测**：现居本仓者 `git ls-files` 末段同名命中恰为 1（含 Amendment 5 新增的 `HarnessPlane_Freeze_Record_Design_v1.md`），创始档案库时代的旧身份仓内零命中、其解析不走文件名而走各自治理记录中的登记身份；但无门保证其持续成立。解析在多候选时报错而非未显式说明就选择，失败方式安全。
- **接受**：本文法生效前既有的设计正本页首与既有流水日志条目的 ID 前缀**一律不回改**——它们按 OD-56 不迁入交付仓，回改无收益且违反不倒写不可变记录的纪律。既有前缀中 `MLS` 被 `milestones-schema` 与 `milestones` 两个对象共用（`MLS-D1` 至 `MLS-D5` 两处并存，同一 ID 指向两份不同裁定）是该缺陷的既有实例，由本文法的目录名前缀规则对新条目防止，历史不倒写。
- **接受**：条目取值固定的条目类型集合的**完备性未经机械证明**。九类的依据是两问原则加对已知失败案例的覆盖，不是穷尽证明。**该闭集已两次被自身证伪**——七类方案漏「不推进生命周期的决定」一整类，八类方案漏「非决定条目」并因多余定语排除了暂缓与拒绝类决定。第三版缩小范围了 `裁定` 的定义并补 `转录`，但**不声称此后不再出现无处安放的条目**；再次出现时应改原则、不应再补格子。
- **接受**：机制区进入公开只读投影时，设计正本页首的 `权威状态` 指针所命名的 subject，其治理记录目录不进入公开面，故该指针在公开面上不可解析。该面归 gov-t13 分发设计（台账 OD-83 open；§9 已列「机制正本内治理引用的处置」），本设计不预判其解法。

## 16. Gate boundary

- 本文档是待 Owner 检查的设计候选，不是 Owner-confirmed Contract，不是 Review PASS，不是 Freeze。
- 本设计的改稿与整改未创建任何新仓内容（就地重写系 OD-80 ③ 授权）；`repo-layout` 评审 subject 已随 r1 送审按标准程序登记（OD-85）。融合三件的 amendment 候选修订属 OD-87 链的独立行为、各有候选行与中间态声明，不是本设计的改动面。
- r2 送审授权与评审配置在案（OD-85/88，gpt-5.6-sol 全轮），评审按过渡执行条款走旧仓通道。r2 送审前置 = 源码单仓化 amendment 链生效——**已满足**（2026-08-20，OD-90：三件 Freeze Record 在锁；先例 = spec-fused r1 送审前置 Amendment 2）。
- Review 后的 finding disposition、remediation、Owner Freeze 各为独立 Gate；定稿形态比照标准链（`docs/governance/repo-layout/` Owner Decisions + Freeze Record 字节锁 + 状态头翻转）。
- **Owner Freeze 完成 gov-t0，不自动授权任何后续任务**：gov-t1 骨架落地、gov-t2 门重建、任何新仓创始动作、commit、push 各为独立授权。
