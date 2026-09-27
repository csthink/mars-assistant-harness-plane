# HarnessPlane 公共技术 Decision 机制设计

> Depends on:
> `spec.md@r5 S-03、FR-14`
> `milestones.md@r11 gov-t25`
> `gov-t25.md`
> `HarnessPlane_Repo_Layout_Design_v1.md`
> `HarnessPlane_Delivery_Method_Design_v1.md`
>
> 权威状态: subject `decision-mechanism`（治理记录目录按所在仓的布局规则解析；唯一状态正本）

本修订（FROZEN r2，2026-09-07）= Amendment 1，Changelog = `changelog/CL-46-handoff-progress-files-decision-single-commit-and-review-matrix.md`；触发 = Owner 2026-09-07 裁定 J6（台账 `repo:OD-10`，减重第 5 步 5b；台账 `repo-od-10:KB-09`）；语义级、全文重写：r1 的节号自本修订起不再有效，节对应关系见该 Changelog 第 3 项。r1 的治理记录续编分卷、两提交仪式、锁面指针规则、授权事件与完成事件分立的状态解析、D-01..07 重立与常设授权毕业归位（后两者已兑现）自本修订起退役，其历史文本由 Git 历史与 r1 的 Freeze Record 承载。

## 1. Purpose

CL-58 已按 Owner 明确指令在本任务分支 re-Freeze r3，语义级，核差形态 owner-review；现行冻结事实 = records/governance/decision-mechanism/freeze-records.jsonl 内 revision 3 的行。本次仅冻结规则，完整 cst-ship 的共享实现、适用验收及启用留后继；下方前序候选说明按其形成时点读取。采用候选身份及终裁字节对应见 records/diagnostics/publish-closeout/2026-09-11/finalization-results.json。

横切多个机制的技术规矩住 `decisions/`，一条决定恰一份文件。本设计回答三个问题：一条决定长什么样（§4）、它怎么活（§5：建立、冻结、修改、退役各恰一次提交）、一条规矩住哪（§3）。机制只造承载：每条决定的内容与存废恒由 Owner 终裁。

## 2. 范围与邻接边界

- 本设计冻结：决定归属路由与判据（§3）；`decisions/` 内部文法：命名、编号、页首、正文骨架、沿革行（§4）；生命周期四事件的提交构成、状态权威、评审插件与 MR 申报（§5）；r1 治理记录的只读历史与切换点（§6）。
- 本设计不冻结、不吞占：修正的分级判据与 Changelog 八项（交付方法 §7.2 / §7.5，本设计只声明 Decision 的修改不建 Changelog）；评审矩阵默认值（交付方法 §8）；Freeze Record 形制（公共 Decision 不建记录行，freeze-record 设计 §3.3）；MR 描述申报规则本体（handoff-protocol 设计 §7，本设计只指出 `decisions/**` 在其触发路径内）；产品决定（proposal / spec）与单机制内裁定（`records/governance/<subject>/`）的内容；每条决定的内容。

## 3. 决定归属路由

| 事项类别 | 唯一归属 | 承载程序 |
|---|---|---|
| 产品决定（需求、范围、产品行为） | proposal / spec | 模板集与交付方法 §7 修正程序 |
| 单机制内裁定（只约束一个 subject 的对象） | `records/governance/<subject>/` Owner Decisions 卷 | 布局权威 §6.6 条目文法 |
| 横切技术规矩（约束多个机制或全仓工作方式） | `decisions/D-<NN>-<slug>.md` | 本设计 §4 至 §5 |
| 未定事项（尚无定稿、等 Owner 拍板） | 进度文件 `open · <id> · OD` 行（handoff-protocol 设计 §3） | `answer` 后按下段毕业搬家 |

同一事实只在一处为正本，其余位置只写指针；判归属拿不准时按 OD 行承载并呈 Owner，不自行落 `decisions/`。**归属判据**：答案需要成节成文、含程序与文法（如任务旅程、交接协议）即机制，走机制单元设计；答案是一条可独立陈述、约束多个机制或全仓行为的规矩（写作纪律、跨任务技术栈钉死、常设授权）即 Decision。边界实例：记进度动作属协议（handoff-protocol），而「工作分支 commit 免逐次授权」是横切授权规矩（`D-08`）。**毕业搬家**：OD 行所载事项定稿为横切规矩时，Owner 认可立项 → 按 §5 建立与冻结 → 该 OD 行以 `answer` 闭合、依据指向 `D-<NN>`；此后全部引用改指编号，OD 行既有正文不改写。

## 4. Decision 文件形制

- **落点与命名**：`decisions/D-<NN>-<slug>.md`（布局权威 §6.3 委托）。`<NN>` 两位起、发出后永不复用、永不重排；`<slug>` 匹配 `[a-z0-9]+(?:-[a-z0-9]+)*`，只作导航。一条决定恰一份文件；修改在同一文件内形成新修订（r<N> 递增），退役不删除文件。`D-01` 至 `D-07` 保留给上一代产品线编号决定的重立件（按需逐条、每条 Owner 终裁，沿用原编号、页首「来源」行写明重立与参照对象），新决定自 `D-08` 起编。
- **页首三行**：`> 状态: DRAFT ｜ FROZEN r<N>（YYYY-MM-DD） ｜ RETIRED（YYYY-MM-DD）`（三值取一）、`> 适用范围: <一句话>`、`> 来源: <立项授权指针>`。禁入：评审轮次、branch / commit / MR、执行状态、其他对象的状态转录。
- **正文四 H2，顺序不可变**：`## 决定`（规矩本体，条款式）、`## 理由`（含否决过的替代）、`## 适用范围与边界`（约束谁、不约束谁，点名最易误吞的相邻面）、`## 沿革`（append-only）。
- **沿革行文法**：`- <YYYY-MM-DD> · <建立|冻结|修改|退役> · <Owner 指令原话> · <依据指针>`。依据指针 = 进度文件内的台账 id、MR、评审证据路径或 Changelog 之一或多个；修改行须写明改动语义与分级申报（`语义级` / `对齐级`）。既有行永不改动，更正开新行引用被更正行。禁入：其他决定的正文副本、实现步骤、运行日志。
- **引用纪律**：别处引用一条决定只写编号 `D-<NN>@rN`（冻结件内恒钉修订）或 `D-<NN>`（不受锁的消费处，指现行修订）；永不抄正文。无机械看守，属评审与人工核对面。

## 5. 生命周期：每事件恰一次提交

| 事件 | 触发 | 提交内容（恰一次 `git commit`） |
|---|---|---|
| 建立 | Owner 认可立项（个案指令或毕业搬家） | 文件入库，状态行 `DRAFT`，沿革一行 `建立`。DRAFT 不得被下游当权威引用 |
| 冻结 | Owner 终裁「冻结 D-NN」 | 状态行 → `FROZEN r1（日期）`，沿革一行 `冻结` |
| 修改 | Owner 终裁「re-Freeze D-NN」 | 新正文 + 状态行 → `FROZEN r<N+1>（日期）` + 沿革一行 `修改`（写明改动语义与分级） |
| 退役 | Owner 终裁「退役 D-NN」 | 状态行 → `RETIRED（日期）`，沿革一行 `退役`（记后继指针，如有）；字节改动仅限页首与沿革 |

- **状态权威 = 页首状态行**，与沿革末行、Git 历史三方一致；三方不一致即缺陷，以 Git 历史重立后以更正行修复。这是 `AGENTS.md` §2「冻结件页首的状态自述只是被审快照」的显式例外（Owner 裁定 J6，台账 `repo-od-10:KB-24`）：Decision 页首只写本对象自身的生命周期状态，每次变化恒由同一提交携带，不存在静默过时路径。无卷、无锁、无 Freeze Record、无 Changelog 义务；修改的语义叙述写在沿革行。
- **评审**：按交付方法 §8 第二句，公共 Decision 的插件 B 默认关、Human 按事实裁量加开（加开时走评审通道 subject 轴 `reviews/decisions-d-<nn>[-amendment-<k>]/`，证据路径写入沿革行）；插件 A 不适用（无规划基线输入）；Human 终裁恒必需、不可拔。
- **对外核差**：`decisions/**` 属 MR 描述申报三的触发路径（handoff-protocol 设计 §7），每个生命周期事件随其 MR 逐件申报旧 / 新字节身份与 Owner 指令原话，Owner 按 handoff-protocol §7 在明确完整交付前或单独人工合并前核差；委托执行不代替 Decision 终裁。
- **消费面**：`RETIRED` 决定不得再被当作现行权威引用；引用它的各冻结件按其自身修正程序对齐，由 Human 排期，stale 引用窗口是已声明残留（交付方法 §7.3 向下语义）。

## 6. 只读历史与切换点

- `records/governance/decisions/` 既有六卷（`decisions-D1` 至 `decisions-D6`）为只读历史：原字节不变、不追加新卷；只读声明的落点 = `records/README.md`。其记载的两提交仪式与锁面动作为历史陈述（`AGENTS.md` §5 解析条款）。
- 切换点 = 2026-09-07 本修订的落地提交。切换点前写入的沿革行按 r1 文法读（第三段为授权与依据指针、第四段为事件后状态），不倒写；切换点后追加的行按 §4 文法。`D-08@r2` 与 `D-09@r1` 的页首状态行已合 §4 文法，字节零改动即合规；两件对 handoff-protocol r4 节号与生成物规则的转录（`D-08` 第 14 行、`D-09` 第 4 条与第 27 行）为过时转录，按 §5「修改」事件对齐、由 Human 排期。

## 7. Rejected alternatives

- **保留每事件一卷**：卷内容与沿革行重复，每次 Decision 事件仍要两个文件；登记本退役后「治理记录为准」对任何冻结件已无机械承载，卷不增加保护。拒。
- **每条 Decision 一 subject 的 `freeze-records.jsonl`**：目录随决定数增殖，`revision` 按 subject 递增与多 Decision 交错编号冲突。拒。
- **状态外置、页首零状态**：设计正本先例的理由（上游状态变化不触发本件、快照静默过时）对自身生命周期状态不成立。拒。

## 8. 最低验收场景

- **S1 · 建立与冻结**：Given Owner 认可一条横切规矩立项；When 执行者以一次提交入库 DRAFT 文件、再以一次提交改状态行为 `FROZEN r1` 并追加 `冻结` 行；Then 两提交各恰含该文件一处改动，页首、沿革末行与 Git 历史三方一致，`git log --oneline -- decisions/D-<NN>-*.md` 恰两条。
- **S2 · 修改**：Given 一条 FROZEN r<N> Decision；When Owner 终裁「re-Freeze D-NN」后以一次提交落新正文、状态行 `FROZEN r<N+1>` 与 `修改` 行（含改动语义与分级）；Then 无卷、无 Changelog、无锁面动作，MR 描述申报三列出该件旧 / 新字节身份。
- **S3 · 退役与编号纪律**：Given 一条 FROZEN Decision；When 以一次提交改状态行为 `RETIRED（日期）`并追加 `退役` 行；Then 该提交对该文件的改动仅在页首与沿革，文件保留，新建决定复用该编号被人工核对拒绝。
- **S4 · 归属判定与毕业搬家**：Given 进度文件内一行 `open · <id> · OD` 所载事项定稿为横切规矩；When 按 §3 判归属并走 S1；Then 该 OD 行以 `answer` 闭合、依据指向 `D-<NN>`，OD 行既有正文零改写。
- **S5 · 切换点兼容**：Given `D-08@r2` 与 `D-09@r1` 现物；When 按 §4 页首文法与 §6 切换点规则读取；Then 两件零字节改动即合规，既有沿革行按 r1 文法可读、不判红。

## 9. 反思

- **必须现在定**：编号与文件的一一对应、永不复用；状态权威 = 页首行（三方一致）；每事件恰一次提交。三条不定则五处留痕会再长回来。
- **同类潜在 bug 一并防止**：页首状态与治理链的层级在 `AGENTS.md` §2 显式写成例外，防「所有冻结件页首即权威」的推广误读（推广与否属台账 `repo-od-10:KB-24`）；沿革行强制含 Owner 原话与依据指针，防裁定只活在会话记忆；毕业搬家强制 OD 行闭合指向编号，防双正本漂移。
- **可接受残留**：引用纪律与编号复用禁令无机械看守，靠评审与人工核对（低）；RETIRED 与消费面对齐之间的 stale 引用窗口（低）；插件 B 默认关后 Decision 修改的语义评审只靠 Owner 核差与按事实加开（中，与交付方法 §8 同源）。
