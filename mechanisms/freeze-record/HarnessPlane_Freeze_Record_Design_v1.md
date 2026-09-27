# HarnessPlane Freeze Record 物理形制设计

> Depends on:
> `spec.md@r5 FR-36、FR-42、FR-43、FR-47、FR-50、SC-6`
> `proposal.md@r5 SC-6`
> `milestones.md@r11 gov-t5、gov-t9`
> `HarnessPlane_Instance_Freeze_Anchor_Design_v1.md`
> `HarnessPlane_Delivery_Method_Design_v1.md`
> `HarnessPlane_Repo_Layout_Design_v1.md`
> `HarnessPlane_Decision_Mechanism_Design_v1.md`
>
> 权威状态: subject `freeze-record`（治理记录目录按所在仓的布局规则解析；唯一状态正本）

CL-55 候选：拟修订 r11，语义级；原冻结基线 r10。本次仅起草，未送审、未 re-Freeze、未启用。完整变更集见 changelog/CL-55-review-evidence-local-archive.md；当前权威仍按 records/governance/freeze-record/freeze-records.jsonl 解析。

最近已冻结基线（历史）：FROZEN r10，2026-09-08，CL-52 语义级变更集。Owner 已核差通过并授权共同 re-Freeze；冻结事实 = `records/governance/freeze-record/freeze-records.jsonl` 内 revision 10 的记录。本次只冻结规则，历史读取与 HEAD 退出能力仍须完成 repo-layout §7.4 的施工与启用条件，不构成施工或删除授权。

前序冻结（历史）：FROZEN r9，2026-09-07，CL-50 第 6b 批语义级 amendment。Owner 已核差通过并授权共同 re-Freeze；冻结事实 = `records/governance/freeze-record/freeze-records.jsonl` 内 `revision 9` 的行。改动范围与已裁例外见 `changelog/CL-50-engineering-documents-and-prototype.md`。

前序冻结（历史）：FROZEN r8，2026-09-07，CL-48，第 6a 批。前序冻结 r7；只对齐保证档案的产品需求退役及直接指针，不改变记录行文法、既有记录或邻接欠账。Owner 已核差通过并明确授权与同批 spec r7 re-Freeze，Changelog = `changelog/CL-48-product-baselines-and-brownfield.md`。

前序冻结修订说明（历史）：本修订（FROZEN r7，2026-09-07）= Amendment 6，Changelog = `changelog/CL-45-artifact-templates-and-schema-retirement.md`；触发 = Owner 2026-09-07 裁定 J7（台账 `repo:OD-10`，减重第 5 步 5a）；对齐级、语义零变化：task-artifact-schema 设计正本已随该步退役，并与另三份工件 schema 设计正本合并为 `mechanisms/artifact-templates/` 模板集，本设计页首删该依赖，§2 / §8 对四类工件 schema 与 Task Definition 保证锚的指称改指模板集，§11 固定输入表登记已落地项。前序 = Amendment 5（FROZEN r6，2026-09-06，`changelog/CL-43-retire-freeze-ritual-and-registries.md`）：r5 及之前的保证档案、引用链传播、两提交仪式与仪式工具条款自 r6 起退役，其历史文本由 Git 历史与 r5 的 Freeze Record 承载。

## 1. Purpose

CL-58 已按 Owner 明确指令在本任务分支 re-Freeze r12，语义级，核差形态 owner-review；现行冻结事实 = records/governance/freeze-record/freeze-records.jsonl 内 revision 12 的行。本次仅冻结规则，完整 cst-ship 的共享实现、适用验收及启用留后继；下方前序候选说明按其形成时点读取。采用候选身份及终裁字节对应见 records/diagnostics/publish-closeout/2026-09-11/finalization-results.json。

本设计定义 Freeze Record（定稿记录）的物理形制：一次冻结 / 定稿事件的冻结事实由一行 JSON 承载，追加进该 subject 的 `records/governance/<subject>/freeze-records.jsonl`。它回答五个问题：一次冻结产生什么、落在哪、何时不可变（§3、§4）；记录承载哪些字段、机器如何取值（§5）；冻结怎么落地、Owner 在何处核差（§6）；Owner Decisions 卷与 Changelog 对记录只引用不转录（§7）；此前 53 份 `.md` 形制记录如何解析（§9）。

上游 `spec.md@r5 FR-36` 的候选到冻结机械可核属性由 `instance-freeze-anchor` 落地，本设计继承其最低锚承载：被冻结字节的精确身份恒在记录内，Owner 对 exact identity 的终裁是记录的唯一来源。

## 2. 范围与邻接边界

- 本设计冻结：记录的落点、命名、物理字节与不可变性（§3、§4）；记录行文法 `freeze-record/v2`（§5）；一次冻结提交的组成与对外申报（§6）；与 Owner Decisions 卷、Changelog、评审证据的衔接（§7）；对象类适用面（§8）；历史记录的解析（§9）；自举（§10）；固定输入（§11）；交付物（§12）。
- 本设计不冻结、不吞占：评审通道内部契约（评审通道设计）；Owner Decisions 卷的条目文法与卷形制（布局权威 §6.6）；proposal / spec / milestones / task / ruling 的生命周期工件模板与非冻结 design 的人工核对模板（`mechanisms/artifact-templates/`，自减重第 5 步起取代四类工件的物理 schema 设计正本）；公共 Decision 的内部文法；受锁字节的机械看守（`locks` 门自 2026-09-06 停用，台账 `repo:OD-10`；本设计不假设任何门读取记录）。
- 本设计正本一件；无工具、无模板、无配图。冻结记录由执行者按 §6 手工建立。

## 3. 核心裁定与总则

### 3.1 一次冻结恰一行不可变记录

每次冻结 / 定稿事件（首冻、re-Freeze 或退役）恰在该 subject 的 `freeze-records.jsonl` 追加一行；该行随冻结提交入仓，此后字节永不改变。文件只追加：既有行不改写、不删除、不重排。冻结之后的新事实（更正、后续裁定）由 Owner Decisions 卷、台账与更晚的记录行承载，不回写既有行。

### 3.2 机械正本

一行记录 = 一个 JSON 对象（§5），是该次冻结事实的机械正本。记录不带人读正文：沿革、最终评审结果及当前残留由 Changelog 承载，完整逐轮过程归档（§7），Owner 决定由 `定稿` 卷承载。散文不得出现记录没有的承重取值（对象身份、修订号、出口）；散文与记录不一致即散文缺陷，机械消费恒读记录。

### 3.3 对象类适用面（总则，细目见 §8）

本形制适用于交付方法 §7.1 修正流水线适用面内的三类对象：治理机制设计正本（Layer 2）、规划基线件（proposal / spec / milestones）、UI 设计冻结件。公共 Decision 与 Task Definition 各由其机制承载既有保证锚，本设计不为其建立记录行。

### 3.4 唯一机械记录

一次冻结事件的冻结事实恰有一个机械正本 = 该次记录行。冻结事实 = 记录行的全部字段（§5.1）。同一冻结事件的其他治理文字对这些字段的取值只引用、不转录：`定稿` 卷条目退化为指针（布局权威 §6.6 第三处最低承载，指针取法见 §7），Changelog 只承载人读语义叙述，其涉及冻结事实的三项（交付方法 §7.2 第 2、7、8 项）只写修订号与记录行指针、不写 bytes / 行数 / SHA-256。

**Owner 决定三项的来源是条目、不是记录**：`instruction`（指令原话）、`exit`（出口）与 `reservation`（保留内容）的唯一来源 = `定稿` 条目，记录把三项转录进行内（转录方向：条目 → 记录）。条目正文除记录指针与 Owner 指令原话外，不另写 subject、修订号、日期、bytes 与 SHA-256。

## 4. 文件形制

### 4.1 落点与命名

```text
records/governance/<subject>/freeze-records.jsonl
```

- 落点 = 布局权威 §6.6 已冻结的治理记录目录；不需布局 amendment。`<subject>` = 对象的治理 subject 名（派生规则同布局权威 §3.2 公理 3）。
- 每 subject 恰一本，JSON Lines，只追加。多件共同构成一个冻结面的对象（如 gates 设计正本族）只追加一行，多件全部列入 `objects[]`。

### 4.2 物理字节

UTF-8，无 BOM；只用 LF；每行恰一个 JSON 对象，无空行，文件以一个 LF 结束。行内成员按 §5.1 表序排列、不换行、不含多余空白；成员名不重复，可被严格解析器解析（拒绝 `NaN` / `Infinity`）。

### 4.3 现行冻结事实的解析规则

两条规则次序固定：**其一**，某 subject 的现行冻结事实 = 其 `freeze-records.jsonl` 内最后一行 `event` 取 `freeze` 或 `re-freeze` 的行（`retire` 行不改变现行修订号；其后若无 freeze / re-freeze 行，`retire` 行的 `objects[]` 所列路径自该行起不在冻结面内）；**其二**，该文件不存在时 = 该 subject 目录下编号最大的 `HarnessPlane_<Subject>_Freeze_Record_r<N>.md`（§9）。同一 subject 内 `revision` 严格递增、永不复用，新行的 `revision` = 现行冻结事实的 `revision` + 1（无论现行事实来自哪条规则）。

## 5. 记录行 `freeze-record/v2`

### 5.1 字段（封闭对象，全部必填；`null` 只在明写允许处）

| 字段 | 类型 / 取值 | 语义 |
|---|---|---|
| `revision` | 正整数 | 本次生效的 FROZEN r`<N>`；`retire` 行取退役发生时该 subject 的现行修订号（与同批 re-freeze 行同值时该 `retire` 行在前） |
| `event` | `"freeze"` ｜ `"re-freeze"` ｜ `"retire"` | 首冻 / 再冻 / 退役。`freeze` ⇒ `previous` = `[]` 且 `changelog` = `null`；`re-freeze` ⇒ `previous` 非空且 `changelog` 非 `null`；`retire` ⇒ `previous` = `[]`、`changelog` 非 `null` |
| `date` | `YYYY-MM-DD` | Owner 终裁日期 |
| `objects[]` | `{path, bytes, sha256}`，≥ 1 | 被冻结对象身份：`path` 为规范仓内相对路径、`bytes` 非负整数、`sha256` 恰 64 位小写十六进制；`path` 在数组内唯一。`retire` 时为被退役件及其最后冻结身份 |
| `previous[]` | `{path, revision, sha256}` ｜ `[]` | 前序身份：re-Freeze 时每个 `objects[]` 成员在前序冻结事实内的身份（本批字节未变化的成员 `sha256` 与 `objects[]` 同值）；首冻与退役取 `[]` |
| `changelog` | 仓内相对路径 ｜ `null` | Changelog 指针（交付方法 §7.2 第 8 项的反向指针） |
| `check` | `{kind, ref}` | 核差锚，二选一：`kind` = `"cross-vendor-review"` 时 legacy-git 的 `ref` 为固定原轮判词路径，archive-v1 的 `ref` 为正式 Changelog 或 ruling 路径加 `#review-result`（评审通道 §8.6.5）；`kind` = `"owner-review"` 时 `ref` = 本次 `定稿` 卷仓内路径。前者要求从同一来源核验原判词、清单与最小结果块（新模式适用），每个 `objects[]` 成员的 `sha256` 在该束清单的 candidate 输入内恰一命中（`FR-36` 相等断言，Owner 核差判定） |
| `instruction` | 字符串 | Owner 指令原话，转录自 `定稿` 条目 |
| `exit` | `"freeze"` ｜ `"freeze-with-reservation"` | 出口；`freeze-with-reservation` ⇔ `reservation` 非 `null` |
| `reservation` | 字符串 ｜ `null` | 保留内容与其位置 |

### 5.2 示例行与读出

```json
{"revision":13,"event":"re-freeze","date":"2026-09-06","objects":[{"path":"mechanisms/gates/HarnessPlane_Gates_Design_v1.md","bytes":63333,"sha256":"<64 位小写十六进制>"}],"previous":[{"path":"mechanisms/gates/HarnessPlane_Gates_Design_v1.md","revision":12,"sha256":"<64 位小写十六进制>"}],"changelog":"changelog/CL-43-retire-freeze-ritual-and-registries.md","check":{"kind":"owner-review","ref":"records/governance/gates/HarnessPlane_Gates_Owner_Decisions_D<N>.md"},"instruction":"re-Freeze gates r13、freeze-record r6、delivery-method r8、gate-conclusion-contract r4","exit":"freeze","reservation":null}
```

读出现行冻结事实的等价最小实现（例示，非交付物）：`python3 -c 'import sys,json; rows=[json.loads(l) for l in open(sys.argv[1],encoding="utf-8")]; print([r for r in rows if r["event"]!="retire"][-1])' records/governance/<subject>/freeze-records.jsonl`。

### 5.3 删掉的旧字段与去向

`record_schema` / `subject`（由文件路径承载）；`object_class` / `matrix_row`（评审矩阵的映射面归交付方法 §8，记录不转录）；`plugins`、`guarantee`、`upstream`（旧 `spec.md@r5 FR-44 / FR-45 / FR-46` 的保证档案与引用链传播，自 r6 起已无生产者；CL-48 同批 spec r7 删除其规范义务并保留退役 ID。实际评审/验证结论、显式插件开关与 Owner 决定仍按各自记录协议保留，不恢复保证等级或上游传播字段）；`locks`（三个登记本转只读历史后无锁面对象）；`review_anchor`（压为 `check`）；`human.decision_ref`（并进 `check.ref` 或由 `定稿` 卷反向指针承载）；`human.ledger_ref`（台账项由 `定稿` 卷页首承载）；`frozen_objects[].locked`（登记本退役后锁面即记录面）。

## 6. 冻结怎么做（一次冻结提交）

1. 候选字节定稿；re-Freeze 时 Changelog 按交付方法 §7.2 起草完毕（其终态字节先于记录行定稿，因 `changelog` 只是指针）。
2. 逐对象取身份：`wc -c <路径>` 得 `bytes`，`shasum -a 256 <路径>` 得 `sha256`；前序身份自现行冻结事实（§4.3）取。
3. 按 §5 追加一行；建立 `定稿` 指针卷（布局权威 §6.6 一裁一件，指针取法见 §7）。
4. **冻结提交** = 含记录行与 `定稿` 卷的一次 `git commit`；尚未入库的候选字节随该提交入库，同分支前序提交已承载的候选字节是该提交的输入；冻结对象的身份恒由记录行 `objects[]` 承载，不由提交边界承载（变更集时该提交含全部成员的记录行与卷，该 Changelog 的终态字节同批入库）。
5. 对外申报走 MR 描述申报三（过渡正本 = `HANDOFF/README.md`，台账 `repo-od-10:KB-06`）：逐件路径、改动类别、旧 / 新 `bytes` + `sha256`、授权依据、分级、复核命令。
6. Owner 人工核差（完整交付在下达“交付”前，单独人工合并在合并前）：按申报三的复核命令逐件复算并与记录行 `objects[]` 比对。

不可减项（Owner 2026-09-06 裁定 E1，减为两项）：Owner 对 exact identity 的终裁、Changelog 的语义化叙述。

## 7. 与治理链的衔接

- **Owner Decisions 卷**：`定稿` 条目正文恰一段，逐项恰为 Owner 指令原话、出口（带保留时含保留内容与其位置）、本次记录行的指针、非授权一句（不授权 push、MR、合并或任务外动作）；锁转换授权句自本修订起不再在场。**记录行指针的取法** = `records/governance/<subject>/freeze-records.jsonl` 内 `revision` 为 `<N>` 的行（写法：`<该文件路径>` + `revision <N>`），不写行号。条目标题 `<标题>` 取 `re-Freeze`（re-Freeze）、`首次 Freeze`（首冻）或 `退役`（退役）。卷页首与条目外形归布局权威 §6.6。
- **Changelog**：第 2 项 = 被修改文件路径 + 原冻结 revision 号 + 原冻结事实的指针（记录行指针，或 §9 的 `.md` 记录路径）；第 7 项叙述核差形态与 Human 处置并引用 `check.ref`；第 8 项 = 新 revision 号 + 本次记录行指针。三项一律不写 bytes、行数与 SHA-256。
- **评审证据**：legacy-git 的旧 check.ref 保留固定 Git 原轮读取，archive-v1 以正式件的 #review-result 为最小 Git 锚，原件由其中 EvidenceRef 按评审通道 §8.6 读取。owner-review 仍指本次定稿卷，不凭外部摘要自动变成 cross-vendor-review。新原件核验失败则不能以原件评审证明身份；Owner 可按既有合法出口重新核差并如实记 owner-review，不能补造 PASS。不得为满足 check.ref 把报告或清单复制回 Git。

## 8. 对象类适用面与既有保证锚

三类对象（§3.3）共用同一记录行文法；对象类不进记录。公共 Decision（decision-mechanism 设计 §5.2：保证锚 = `定稿` 卷 + Git history）与 Task Definition（`task.template.md`：保证锚 = finalization ruling + Git 历史）维持各自裁定，不建记录行；decision-mechanism 设计内仍写两提交仪式与登记本指针的条款推到减重第 5 步（台账 `repo-od-10`）。

## 9. 历史记录

- 53 份 `records/governance/<subject>/HarnessPlane_<Subject>_Freeze_Record_r<N>.md` 是不可变历史：原字节不变、不重命名、不补造 `freeze-record` 围栏；其解析优先级 = 自身 `freeze-record` 围栏（在场时，`freeze-record/v1`）> `records/governance/freeze-record/HarnessPlane_Freeze_Record_Alignment_Inventory_v1.json` 条目（雏形记录）。
- 对齐 inventory 保留为历史件，不重算、不扩充；其 `design_identity` 是建立时点事实。
- 三个登记本（`records/evidence-locks.jsonl`、`records/lock-declarations.jsonl`、`records/authorizations.jsonl`）自 2026-09-06 起为只读历史档案（Owner 裁定 E8，台账 `repo:OD-10`）：无工具写入、无门读取；`lock-declarations.jsonl` 内 `lock` 行自该日起不再与工作区字节对应。只读声明的正本 = `records/README.md`。

### 9.1 固定历史来源（CL-52）

§9 历史 `.md`、旧对齐 inventory 与退役登记本可在 repo-layout §7 的逐组授权与启用条件全部满足后退出 HEAD，以共同读取器按固定 commit + 原路径读取，原记录和 inventory 不重算、不回写。解析仍先用原件围栏、再用同一明确来源的对齐 inventory；不以新版 inventory 静默解释旧原件。

现行冻结事实的 §4.3 优先级不变：JSONL 存在时依原规则取 freeze/re-freeze 记录；没有 JSONL 时编号最大的旧 `.md` 仍承载当前事实，该件继续在场。所有现存 JSONL 的全部行及当前正式决定保持在场；当前 check.ref 所指旧评审原件在 CL-55 切换后允许按固定 Git 来源读取，不以本条删除历史行或 retire-only 文件。历史 check.ref 使用固定原引用定位，缺原件或字节不符明确未查成；不补造 Freeze Record。调用方 `current_freeze_fact` 不把读取失败改为零修订或空结果。

新增施工验收：旧记录与原 inventory 固定读取后解析结果相同；无 JSONL subject 的当前 `.md` 保留；JSONL 含 retire 行仍按原次序解析；缺件、旧模式不兼容或哈希失配保持失败。共同 helper 归 repo-layout，本 subject 不新增第二读取器。

### 9.2 CL-55 核差与兼容验收

freeze-record/v2 行的键与 kind 闭集不变，ref 的新片段定位只适用于新 archive-v1 正式件。解析器须区分原路径与 #review-result，拒绝未知片段、多结果块、摘要与归档不符、候选集合缺成员及字节不等；旧行不批改。最小结果块位于 Changelog 或 ruling，不改变 Owner 定稿卷一段指针的形制，不在卷里复制 object 身份。只读 current_freeze_fact 仍可从 Git 读取冻结事实，无需默认访问私人原件；显式核差必须验证所依赖原件及副本，未查成不报告通过。

## 10. 自举与首个实例

本修订（r6）自身的记录行按本形制手工建立，并与同批变更集成员（gates r13、gate-conclusion-contract r4、delivery-method r8）的记录行及各成员的 `定稿` 卷落同一次冻结提交（§6 第 4 步：尚未入库的候选字节随该提交入库，同分支前序提交已承载的候选字节是该提交的输入），是本形制与「冻结 = 一次提交」的首个实例（Owner 2026-09-06 裁定 E1）。r6 行的 `previous[]` 取 r5 记录的 `frozen_objects` 身份（§4.3 其二）。

## 11. 对邻接权威的固定输入

| 权威 | 处置 | 固定输入 |
|---|---|---|
| 布局权威 §6.6 | 本修订零改动；其 §6.6 条目闭集与 §14 Gherkin 内的锁转换授权句、「登记本的 `authorized_by` / `declared_by` 仍指向该文件」句按 `AGENTS.md` §5 解析条款读为历史陈述 | `定稿` 指针的取法改为记录行指针（§7）；条目闭集不再含锁转换授权句。对齐欠账登记台账 `repo-od-10` |
| 交付方法 §7.2 / §7.5 / §7.6 | 同批 amendment（变更集成员） | 第 8 项「或等价」= 新修订号 + 记录行指针；§7.5「锁转换两提交仪式」删、「每 subject 一份 Freeze Record」改「一行冻结记录」；§7.6「仪式」条改为一次冻结提交 |
| 评审通道设计 §6.2 域一 | 已随减重第 3 步落地（评审通道设计 Amendment 4，`changelog/CL-44-review-channel-verdict-simplification-and-data-source-retirement.md`） | 在案修订号核对的扫描域改为 `records/governance/*/freeze-records.jsonl` 逐行 + 历史 `.md`（§4.3 次序）；`archive-revision` 与 `locked-reference` 两族的数据源已冻结 |
| handoff-protocol 设计 §6.3 | 推后至减重第 5 步（Owner 裁定 E7） | 申报一触发条件恒不成立；申报三升为正文并含「本次 MR 含冻结提交」触发条件 |
| decision-mechanism §4.5 / §5.3 / §5.4 | 推后至减重第 5 步 | 两提交仪式与登记本指针条款退役 |
| `AGENTS.md` §3 / §5 | 按其自身授权同批更新 | 第六条例外改指本修订；§5 删两提交仪式条、加只读档案声明与解析条款 |

## 12. 交付物清单

本正本一件；冻结批同批 = 本 subject 记录行（r6）、`定稿` 卷、受管清单再生成（`manifest --write`）。Amendment 4 的三件工具交付物（`cst_freeze.py`、`cst_freeze_selftest.py`、.agents/skills/cst-freeze/SKILL.md）随本修订删除。

## 13. Rejected alternatives

- **全仓一本 records/freeze-records.jsonl**：否决（Owner 裁定 E3）。并行分支（D-09 上限 4）同时追加末行必冲突，且违反「一 subject 一目录」的派生规则。
- **每 subject 一文件覆盖、只留现行**：否决。丢失沿革，与 §3.1 不可变直接冲突。
- **保留 `.md` 六节形制、只退仪式**：否决（Owner 裁定 E2）。`cst_freeze.py` 是该形制唯一生成器，保留形制即保留服务于已退役语义的实现或手写千行记录体。
- **记录行并入 `定稿` 卷**：否决（Owner 裁定 E4）。须布局 amendment，且失去 JSON Lines 的机械可读面。
- r5 及之前的否决项 A 至 J 随其所属条款退役，为历史。

## 14. 最低验收场景

- **S1 · 首冻追加**：Given 某 subject 首次冻结、目录无 `freeze-records.jsonl`；When 建立记录；Then 新建该文件并恰含一行，`revision` = 1、`event` = `freeze`、`previous` = `[]`、`changelog` = `null`，该行与 `定稿` 卷同一提交（尚未入库的候选字节随该提交入库，§6 第 4 步）。
- **S2 · 再冻追加**：Given 现行冻结事实为 r3（来自 jsonl 或 `.md` 记录）；When re-Freeze；Then 追加一行 `revision` = 4、`event` = `re-freeze`，`previous[]` 逐路径等于 r3 的对象身份，`changelog` 非 `null`；既有行字节不变。
- **S3 · 退役追加**：Given 冻结面内两件被删除；When 退役；Then 追加 `event` = `retire` 的行，`objects[]` 为被退役件的最后冻结身份、`previous` = `[]`；该行不改变现行修订号，其后的 re-freeze 行 `objects[]` 不再含该路径。
- **S4 · 解析规则两条次序**：Given subject A 有 `freeze-records.jsonl`（末行为 `retire`），subject B 只有 `.md` 记录 r2 与 r10；When 求现行冻结事实；Then A 取其文件内最后一行 freeze / re-freeze 行；B 取 `HarnessPlane_B_Freeze_Record_r10.md`，B 的下一行 `revision` = 11 并新建其 jsonl。
- **S5 · 记录不可变、不回写**：Given 某行的 `reservation` 事后需更正；Then 不改该行，更正以 Owner Decisions 条目登记并由更晚的记录行承载；对既有行的任何字节改动即违规。
- **S6 · changelog 指针存在**：Given `event` 为 `re-freeze` 或 `retire`；Then `changelog` 所指路径在同一提交内受跟踪且非空；Changelog 第 2 / 8 项只写修订号与记录行指针，写出 bytes / 行数 / SHA-256 即违反 §3.4。

## 15. 反思

- 必须现在定：一冻一行、只追加不回写（否则沿革与不可变同时失守）；两条解析规则的固定次序（否则 53 份历史记录与新文件并存期无准绳）；`check` 二选一（否则 Owner 核差形态在记录内不可见，`FR-43` 留痕落空）。
- 同类潜在 bug 一并防止：`retire` 行被读成现行冻结事实（§4.3 其一排除）；并行分支同写一本（每 subject 一本）；Changelog 转录身份后漂移（§3.4 指针形态）。
- 本批处置：原 FR-44 / FR-45 / FR-46 需求删除欠账由 CL-48 的 spec r7 同批冻结承载，旧字段的历史来源与实际证据保留边界见 §5.3。
- 可接受残留：记录行无任何机械看守，合规靠 Owner 核差（中）；评审通道对本形制记录不在案（减重第 3 步，中）；UI 设计冻结件本仓尚无实例（低）。
