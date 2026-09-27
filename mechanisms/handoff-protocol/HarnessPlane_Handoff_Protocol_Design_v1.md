# HarnessPlane 会话交接与执行记录协议设计

> Depends on:
> `spec.md@r7 S-03、FR-39`
> `milestones.md@r13 gov-t26`
> `tasks/gov-t26/gov-t26.md`
> `HarnessPlane_Repo_Layout_Design_v1.md`
> `HarnessPlane_Delivery_Method_Design_v1.md`
>
> 权威状态: subject `handoff-protocol`（治理记录目录按所在仓的布局规则解析；唯一状态正本）

本次候选：r10，2026-09-08，CL-54 语义级 amendment，起草授权与变更语义见 `changelog/CL-54-s16-client-acceptance-boundary.md`。本候选未 re-Freeze，S16 验收边界与对应操作说明按 §6.4 分阶段生效；不新增运行接口版本。

起草基线（现行冻结事实）：FROZEN r9，2026-09-08，CL-53；冻结事实 = `records/governance/handoff-protocol/freeze-records.jsonl` 内 revision 9 的记录。r9 被审快照的页首候选措辞不改变该冻结事实。CL-53 共享实现已切换为 handoff/v2、request/v2、status/v3；既有验收证据和本次候选的验收条件分开解析，S16 的后继支持范围仍以真实结果为准。

前序冻结（历史）：FROZEN r8，2026-09-08，CL-52 语义级变更集。Owner 已核差通过并授权共同 re-Freeze；冻结事实 = `records/governance/handoff-protocol/freeze-records.jsonl` 内 revision 8 的记录。本次只冻结规则，历史读取与 HEAD 退出能力仍须完成 repo-layout §7.4 的施工与启用条件，不构成施工或删除授权。

前序冻结（历史）：FROZEN r7，2026-09-07，Amendment 6，CL-49，语义级。Owner 已核差通过并授权共同 re-Freeze；冻结事实 = `records/governance/handoff-protocol/freeze-records.jsonl` 内 `revision 7` 的行。设计已冻、实现未交付；新命令与新事件按 §6.4 的实现切换条件启用，期间使用兼容的 result/note 形制，不宣称新版自动交接已可用。

前序冻结（历史）：FROZEN r6，2026-09-07，变更集 `changelog/CL-47-optional-governance-lint.md`。Owner 已核差通过、接受本次次序偏离，并授权本变更集 re-Freeze；冻结事实 = `records/governance/handoff-protocol/freeze-records.jsonl` 内本次 `re-freeze` 记录。修改只覆盖 layout / manifest 可选化及直接消费者，原第 6 步范围不在本次展开。

前序冻结修订说明（历史）：本修订（FROZEN r5，2026-09-07）= Amendment 4，Changelog = `changelog/CL-46-handoff-progress-files-decision-single-commit-and-review-matrix.md`；触发 = Owner 2026-09-07 对减重第 5 步规划的裁定 J2 至 J5 与 J13（台账 `repo:OD-10`，5b）；语义级、全文重写：r4 的节号自本修订起不再有效，节对应关系见该 Changelog 第 3 项。前序 = Amendment 3（FROZEN r4，2026-09-05，`changelog/CL-38-handoff-protocol-d08-r2-transcription-alignment.md`）。r4 及之前的三类记录、锚点文法、恢复对账六步、历史名「片段」与汇编、历史名「封口」的五条判据与校验器条款自本修订起退役，其历史文本由 Git 历史与 r4 的 Freeze Record 承载。

CL-55 候选：拟修订 r11，语义级；原冻结基线 r10。本次仅起草，未送审、未 re-Freeze、未启用。完整变更集见 changelog/CL-55-review-evidence-local-archive.md；当前权威仍按 records/governance/handoff-protocol/freeze-records.jsonl 解析。

## 1. 目的

CL-59 已按 Owner 明确指令在本任务分支 re-Freeze r15，语义级，核差形态 owner-review；现行冻结事实 = records/governance/handoff-protocol/freeze-records.jsonl 内 revision 15 的行。原统一执行器要求由 skill-only 规则替换，运行与安装状态见 HANDOFF/README.md；CL-58 原始决定和对象身份保留在原记录及 records/diagnostics/publish-closeout/2026-09-11/finalization-results.json。下方前序候选说明按其形成时点读取；本次候选到终裁的身份核对见 records/diagnostics/publish-closeout/2026-09-11/skill-only-finalization-results.json。

CL-56 正式候选：拟修订 r12，原冻结 r11，语义级；起草依据 HANDOFF/progress/repo-od-10.md:668。本文件是 candidate-map.json 指向的正文候选，未生效；现行权威按正式路径及治理记录解析。下方前序候选/冻结说明均按原时点作为沿革读取。

Agent 会话有寿命：上下文会耗尽、进程会中断。本协议规定会话之间传递现场的唯一记录形制：每个任务一份只追加的进度文件、现算读取器、只读接力与共用收尾过程。它同时是编排者与多 executor 形态（`records/diagnostics/reduction-batch-3/2026-09-06/enhancement-plan-addendum-2.md` §2）的并发记录形制，两者是同一份，不是两套。

## 2. 范围与边界

- 本设计冻结：任务的分类与编号、进度文件的落点与行文法、开放项的铸造与闭合语义（§3）、接力规则（§4）、记进度与常设授权（§5）、现算命令与可选核对（§6）、MR 描述申报（§7）、与编排者及反馈队列的接口（§8）、只读历史与切换点（§9）。
- 本设计不冻结、不吞占：任务终态的正本（`tasks/<task-record-id>/rulings/`，`ruling.template.md`）；台账任务的开工授权与承载台账项的处置指令（Owner 个案）；反馈队列本体与编排者的派发、回收、晋升程序（增强阶段）；M-04 运行态存储（`spec.md@r7 FR-26 / FR-27 / FR-31`）；`HANDOFF/` 的落点（布局权威 §6.7）。
- **Owner 2026-09-06 约束（逐字）**：「编排者与全部 subagent 的状态与交接记录，必须在多个会话同时写入时保持不冲突。任何使两个 subagent 会话写同一个文件的设计一律拒绝」。本设计的落法：一任务一文件、每个会话只写自己任务的进度文件、快照由命令现算而不是被维护的文件。并发无冲突因此是结构性质而不是校验结果：两个会话的写入落在两个不同路径，Git 合并对不同路径的追加没有冲突面；对同一开放项的闭合是集合语义（§3 闭合语义第 2 条），与写入位置和合并顺序无关。r1 至 r4 的分片与折叠模型即为此建立，本修订减掉的是层数与仪式，不退回单文件整篇覆盖的单会话形态。

## 3. 任务与进度文件

**任务的分类与编号**。记录单位叫任务，分三类，类别由仓内事实判定：

- **里程碑任务**：登记在 `sdd/milestones.md` 的任务，编号 = task record ID（如 `gov-t11`），有 `tasks/<task-record-id>/` 与 Definition；终态 = `tasks/<task-record-id>/rulings/` 内页首 `Type` 为 `done` 或 `close` 的裁定件在场。
- **台账任务**：从某台账事项开工的工作（冻结件修正、台账项处置等），编号 = 承载台账项编号的小写形态（`repo:OD-10` → `repo-od-10`，`legacy:KB-09` → `legacy-kb-09`）；无 Definition；开工授权 = Owner 对该承载项的处置指令；终态 = 承载台账项闭合（本节闭合语义第 2 条）。
- **仓级**：固定编号 `repo`，承载不依附任何任务的仓级事项；无终态；其进度文件的写入须有 Owner 授权动作伴随。

**落点**。进度文件 = `HANDOFF/progress/<任务编号>.md`，一任务一文件、只追加；随首行事件出生、随首次提交进入 Git，不预建空文件；终态后保留、不删除。`HANDOFF/` 其余成员 = 仓根 README（指针与操作摘要）与只读历史（§9）。落点属布局权威 §6.7 既冻结的语义范围，不需要布局 amendment。

**文件文法**。首两行固定：第一行 `# task: <任务编号>`；第二行为类别行，取三种之一：`- 类别: 里程碑任务 · 名单项 <task-id> · 分支意图 <branch>`、`- 类别: 台账任务 · 承载项 <ledger id> · 分支意图 <branch>`、`- 类别: 仓级`。类别行分支是出生时的工作意图，不是当前现场；新 context 存在时按其解析。分支字符串仅用于 Git 定位与写入归属核对，不用命名形状判授权或成果。成果由提交可达性证明（交付方法 §6.4）。其后每行一个事件：以 `- ` 起始，字段以 ` · ` 分隔、每个字段非空且无首尾空白；首字段为时间（`YYYY-MM-DDTHH:MM`，本地时区，可带 `Z` 或 `±HH:MM` 偏移，偏移不参与任何判据），次字段为行型，行型及其字段如下表；空行允许；文件为 UTF-8 无 BOM、无 CR、末尾恰一个 LF：

| 行型 | 其余字段 | 语义 |
|---|---|---|
| `intent` | `<步骤名> · <一句>` | 关键动作开始前先落；步骤名为 ASCII 字母数字与 `.`、`_`、`-` 组成的串（首字符为字母数字） |
| `result` | `<步骤名> · <一句>[ · commit:<40 位小写十六进制 SHA>]` | 步骤收口；建议带 commit 锚，接力据以核对（§4） |
| `note` | `<文本>` | 疑点、备忘、对既有行的更正（引用被更正行的时间戳与行型，不改旧行） |
| `open` | `<id> · OD ｜ KB · <题名> · <一句>` | 铸造开放项。OD = 等 Owner 的工作项，一句写「被什么挡住」；KB = 已知坏点，一句写现状 |
| `answer` | `<id> · Owner 原话「…」[ · until <YYYY-MM-DD>]` | 只对 OD；Owner 原话逐字；即闭合。`until` 记 Owner「以后再说」的到期日 |
| `close` | `<id> · <依据>[ · commit:<SHA>]` | 闭合任意 id（含他任务与 `legacy:` 前缀的 id），依据为一句事实或指针 |
| `context` | `<单行 JSON 对象>` | 获授权的工作上下文，文法见 §3.1 |
| `handoff` | `<单行 JSON 对象>` | 共用收尾记录，文法与提交证据见 §3.2 / §5 |

新增事件仅在生效后使用；先按字面「 · 」切分首字段与行型，context/handoff 的剩余字节整体解析 JSON，不把 JSON 字符串内部的分隔符再切成字段。

禁入：任何 live Git 状态断言（HEAD、工作区干净与否、ahead / behind、MR 与 pipeline 状态）；运输步骤（commit / push / MR / 合并 / 整理）作为步骤名；一手事实正文的副本（只写指针）。既有行永不改动，错了追加 `note` 更正。

**id 铸造**。`open` 行铸造 `<任务编号>:OD-<NN>` 或 `<任务编号>:KB-<NN>`：前缀逐字等于所在文件名 stem，`<NN>` 两位起、OD 与 KB 各自严格递增、永不复用、永不重排；不含切换点转录行的文件自 01 起连续，含转录行的文件只核严格递增（§9）。前缀规则的唯一例外 = §9 转录行内的 `legacy:` 前缀，只允许在 `repo.md`。全局引用形态恒为完整 id。

**单写者与闭合语义**：

1. 每个会话只写自己任务的进度文件，无例外；对他任务铸造的 id 的 `answer` / `close` 同样写在自己任务的进度文件内。
2. **闭合 = 任一进度文件内存在该 id 的 `answer` 或 `close` 行**。这是集合语义：与行的所在文件、书写顺序、合并顺序无关；多条闭合行全部有效、全部保留，不存在「哪条生效」的仲裁。闭合后的新事实以 `note` 追加，不重开、不复用 id。
3. 台账任务的终态 = 其承载台账项按第 2 条闭合；里程碑任务的终态由裁定件承载，进度文件不自报终态。

### 3.1 context 文法与解释

`context` 的 JSON 闭集键为 `version`、`source_branch`、`target_branch`、`base_commit`、`authority_ref`，全部必填。version 恰为整数 1（布尔不是整数）；source/target 为非空 Git 合法短分支名且不同，本仓 target 固定 main；base_commit 为已存在的完整小写 SHA，代表该批获授权开工的基线；authority_ref 为非空仓内事件或裁定定位，指向授予这次工作范围的事实。它不是授权生成器，会话仍须核对当前用户授权与权威。

context 在首批工作或同一任务换分支时追加，先于业务动作；旧类别行与旧 note 不改。当前分支已有唯一有效 context 时不重复追加。同一任务不得由不同活动会话同时追加；分支冲突或来源不明时停报，不按时间戳择胜。

生效前的历史 note 不机械解析为 context；首次迁移需会话根据 Owner 已授工作意图建立新行，不把「当前碰巧在哪」当授权。事件按文件内顺序生效，不按时间戳排序。base_commit 必须是 source 的祖先；它提供批次范围，不要求 target 停留在该提交。

### 3.2 handoff 文法与解释

以下文法沿用 handoff/v2 写入及旧 v1 只读兼容；skill 不改变事件格式。

`handoff` 按 version 分别验证闭集：version 1 的键为 `version`、`mode`、`content_commit`、`summary`、`evidence`、`entries`、`next`；version 2 在该集合上增加 `after_merge`。各版本自己的键全部必填，不相互补字段；version 只能为整数 1 或 2，布尔不属于整数。旧 version 1 只兼容读取；§6.4 启用后新写事件恒为 version 2。mode 为 `pause` 或 `mr`；content_commit 为 §5 内容提交 C。所用 context 仍为同一文件内该行之前最近的合法 context/v1；没有 context 即该事件无效。

- summary 闭集键为 `completed`、`remaining`，值均为字符串数组，允许空数组但每个元素非空；只写交接写入时的成果与残留声明，不复制一手权威正文，不宣称任务终态。展示时标明其历史时点，不把 remaining 内的合并等待句重新当作当前 next，也不根据本批进入 main 推断其他残留已完成。
- evidence 是去重的对象数组；每项闭集键 `commit`、`path`、`locator`。commit 为完整小写 SHA，path 为该提交中存在的 Git 跟踪文件，locator 为非空节号/行号/事件定位；全部 evidence 提交必须是 C 的祖先或 C 本身。mr 至少一项，pause 可以为空且明确无已核证据。引用真实性由调用方核对，路径可达性由工具复核。
- entries 是去重的对象数组；每项必含 `path`、`role`。role 为 `current`、`history`、`generated`。current/history 不允许其余键；generated 另必含 `sources`（去重、非空路径数组）与 `generator`（非空 argv 字符串数组）。路径都必须在 C 中存在；generated 的源须在 entries 中列为 current 或 history。没有本批入口时允许空数组，不强迫登记无消费者的文件。
- next 闭集键为 `kind`、`text`、`authority_ref`。kind 为 `wait-owner`、`continue-authorized`、`none`；wait-owner 的 text 为唯一建议指令且 authority_ref 为 null；continue-authorized 的 text 为一步动作且 authority_ref 指向已有授权；none 的 text 和 authority_ref 均为 null。事件顶层 next 表示 H/C 尚未被证明进入本地 target 时的源阶段建议；是否可作为当前建议由 §4.3 选择。该对象用于呈报，不执行动作，不替代任何授权门。
- after_merge 仅属于 version 2：pause 必须为 null；mr 必须是闭集对象，键为 `next`、`basis_ref`，全部必填。内部 next 与上一条同文法，表示 H/C 已被证明进入本地 target 后的建议。basis_ref 为非空仓内定位字符串，指向 C 中支持该建议的计划、Owner 事件或裁定；即使内部 next.kind=none，仍须说明无后续建议的依据。none 不改变任务终态，缺失建议不能用 none 隐藏。basis_ref 是建议依据，不是授权；wait-owner 的 authority_ref 仍为 null。

version 2 中 after_merge.basis_ref 及两个 next 内实际存在的 continue-authorized.authority_ref 均须在 C 中定位，其对应路径列为 entries 的 current。定位可使用既有仓内 path#locator、path:line 或完整台账事件 id；台账 id 须能唯一确定来源事件和路径，不能按多处提及任取一处。引用本任务进度时必须用 path:line 指向 C 中已存在的具体合法事件，不能指向尚待生成的 H。工具核结构、路径、事件定位和 §4.2 的后继变化；正文是否足以支持建议及授权是否仍适用，由会话和 Owner 核差。旧 version 1 维持原定位检查，不追补新字段或 entries。

没有建议的依据时，不从 summary、历史 intent、文件时间、分支名或开放项顺序猜测。调用方应先把可支持的建议及依据纳入 C；不能满足 mr 输入时停止准备，不自动编造 none 或转为已授权动作。

所有 JSON 对象拒绝重复键、未知键、未知版本和类型不符。数组中的非空字符串不可只有空白，不含原始换行或控制字符。路径必须为 POSIX 仓内相对文件路径，不含 `..`、空组件、反斜杠或绝对路径；不得指向越界 symlink、Git 元数据、本地 attempts 或凭据。authority_ref/basis_ref/locator 为定位字符串，不是可执行命令。

generator 记录命令供复现，不能因其写在文件里就自动执行。自动运行须同时在本次请求的精确授权命令集合内、来自已核对的仓内入口，按 argv 启动且不用 shell 展开；运行后只能改声明的本批产物。越界改动停报，保留现场。

开放项、终态与 next 分开：open/answer/close 与 ruling 仍是唯一闭合来源，handoff 的 summary/next/after_merge 不改变其事实。无 context/handoff 结构化事件的历史任务保持 legacy 读取；有 version 1 handoff 的任务不因缺少 after_merge 被改判 legacy，不根据散文补造新字段。

## 4. 接力

本节是本仓 `$resume` 的专用优先规则。通用技能中的「必须等于旧工作分支 / HEAD 必须等于 handoff 提交」表只作为无本项目规则时的回退，不能覆盖本节。接手全过程只读：不 fetch、checkout、commit、续写 intent、接管他人 worktree 或启动下一任务。恢复完成只呈报，继续工作需其适用授权。

本节只读义务的执行主体为被测会话、它调用的工具、仓内读取器及这些调用的子进程。它们不得写仓内文件（含跟踪、未跟踪和忽略文件）、修改 HEAD 或 index、创建或变更分支、tag、远端跟踪引用与 worktree 登记，不得通过内部 Git 引用写入、fetch、push、发布或改变治理状态规避只读要求。仅按命令名称判断“通常只读”不足以授予任意参数组合权限；客户端实际启动许可按 §10 S16 核对。

宿主独立维护的会话日志、客户端索引和内部 Git 观测引用按 §10 S16 留取差异与来源证据；这不豁免被测执行主体的写入，也不允许宿主改变仓内文件、HEAD/index、分支/tag/远端跟踪引用或恢复证据后仍判通过。来源不明即待核，不能仅凭引用前缀或对象相同将其排除。这里的分类用于真实客户端验收，不改变 §4.2 的现场拒绝条件或 S20 的隔离工具零写入要求。

### 4.1 选择任务

1. 用户明确指定 task 或已授权任务 worktree 时，以该选择为准；指定 task 必须存在，不能被其他任务替换。
2. 未指定 task 且当前为任务 worktree 时，从当前分支可达记录中找 source_branch 命中当前分支的有效 context；恰一任务时选中，多任务命中为歧义。
3. 未指定 task 且当前为主 checkout 的 main 时，沿本地 main 的 first-parent 历史从新到旧找首次引入有效 handoff 事件的提交边界；每个边界用相对第一父提交的进度文件新增行判定，无第一父时以空树比较。该边界只含一个任务时选择它，同一任务多行取文件中最后有效行；含多个任务时仅列该边界候选，等待用户选择，不继续向更旧边界猜测。普通 merge 查第一父差异、fast-forward 查引入事件的源提交，因此不依赖 merge commit 一定存在。
4. 无新版事件时输出 legacy 简报：只从用户指定的旧任务读取其 result 锚；未指定且旧候选多于一项时请求选择，不假称实现新版自动定位。detached HEAD、找不到任务或上下文冲突时输出具体原因，不自动切换。

选择的是本次接手简报对象，不是后续施工排期。已终态任务也可成为最近交付的简报对象，不能因为已从在办列表消失就丢弃其交接；其他活动任务单列，不用它们的历史 SHA 约束当前任务。

### 4.2 证据与位置

读取所选任务的进度尾部、Definition（里程碑任务）或承载项及其相关事件（台账任务），再按 §5 验证最近 handoff 的 C/H 关系；验证来源为 Git 提交树，不以工作树的 FROZEN 或 prose 自报成立。

- H、C 均为本地 target/main 的祖先：从 main 读取本批；source 分支不存在属于正常清理结果。main 晚于 H 不构成错误，但须比较 H 至 main 对本任务进度、evidence 和 current/generated entries 的改变（version 2 含建议依据与授权定位对应的 current 路径）。后来只追加合法 answer/close 时重算开放项；存在新 context/handoff 时取其后继；新 context 后尚无 handoff 时只报本批未交接，不复用前一批 next；无对应交接的当前材料变化则呈报差异，不能说旧交接仍完整。
- H 仅在 source：当前 worktree 与有效 context 一致时读取中途现场；另有 worktree 承载该 source 时报告精确路径，不读其未提交文件、不切换、不接管。
- source 消失但 H/C 未进入 main，或 H/C/证据缺失、关系不合法：证据不足，停报。不能用「分支删除」「树相似」或一条旧完成描述代替祖先证明。
- 所选工作区有未知改动、HEAD 与 target 分叉、上下文不唯一、浅历史不足以核证据：明确未查成或差异，不自动 hydrate/fetch/stash/reset。记录中的已知本地未提交残留也不能当成已持久化成果。

尚无新 handoff 时，最近带 commit 的 result 仍以 `git merge-base --is-ancestor <SHA> HEAD` 核；无锚只作线索。已完成 result 对应的 intent 不是下一步。legacy 的下一步标「未提供结构化交接，待核对」，可以展示历史 intent 但不得当执行指令。

本任务进度的引用遵守只追加例外：C 中所引事件必须存在；C→H 的合法 handoff 追加不使其失效；H 后仍核原进度前缀和后继事件，不以该文件整体哈希变化拒绝合法追加。后来只追加合法 answer/close 时按原规则重算开放项，不将其自动当作继续授权；会话须核查这些事件对建议适用性的影响。其他建议依据/授权引用路径若有未交接变化，按敏感材料变化停报。

本地 main 与 origin/main 均是本地已知事实；没有实际远端读取，不宣称实时远端一致。恢复默认不调用网络。新会话报告恢复来源、交接时的成果与残留、开放决定和按下节选择的当前 next，不要求用户再次粘贴旧会话解释。

接手摘要必须与该次现算结果及已核来源相符，区分交接写入时的声明与本次已验证事实；不得把“待验”写成“已验”，或把已进入本地 main 推为已完成例行整理。默认不转录全仓开放项总数；确需数量时，从同一次 status JSON 的 `pending_owner` 等相应数组计算，保留同次来源，不凭记忆或手数补总数。已有数组、版本和输出字段不变。摘要自行给出的任务标识、C/H、数量、状态、next 和依据均须在验收时核对原始输出；只命中正确建议文字不足以判整体通过，验收者不能改写回答或补提示后把修正文本冒充原始答复。

### 4.3 当前下一步的选择

下表为现有建议选择规则。调用会话须将交接写入时建议与实际 Git/平台事实分开；已完成的历史运输动作不重复执行。

先按 §4.1 选任务、§4.2 核有效 H/C 和位置，成功后才选当前 next。普通四段、显式 --task、resume 与 JSON 复用同一证明和选择结果；同一任务的 content_commit、handoff_commit、context、原 handoff、summary 与当前 next 必须来自同一有效交接。若 main 有后继有效 H，先完整验证该 H 再替换所有相关结果；本地有更晚未交接 context 或材料时仍停报，不能退回旧 main 建议。

| 证据与事件 | 当前 next | 呈报 |
|---|---|---|
| H/C 未进入本地 main，source 位置合法，version 1 或 2 | 事件顶层 next | 仅为本地源阶段建议，不证明实时 MR 状态；不提前跳过核差/合并 |
| H/C 已进入本地 main，version 2 且 mode=mr | after_merge.next | 说明本地祖先证明及原记录中的 basis_ref；source 仍在或已删不改变选择 |
| H/C 已进入本地 main，version 1（任一 mode）或 version 2 pause | null | 「交接已进入本地 main；未提供合并后下一步，待核对」；恢复可为 ready，不能回放原 next 或补造 none |
| 选择歧义、证据不足、他 worktree 不可接管、未知版本或未交接后继变化 | null | 保留 §4 / §6 的失败状态与具体原因，不呈报旧建议为当前动作 |

选中的 next.kind=none 是显式对象，其 text/authority_ref 为 null，表示本批没有后续动作；它与缺失建议的 null 区分。终态任务也可呈报交付接力，但不得根据 handoff 重开原任务或自动选择其他任务。

该选择不查询托管平台、不核实时 MR/PR 或例行整理完成情况，也不生成执行权。当前 checkout 名、源分支删除、树相似、summary 中的完成描述或 next.text 中是否含「合并」均不能代替 H/C 祖先证明。本地 main 尚未更新时保留本地限制；squash/rebase 导致 H/C 不可达时仍拒绝，不重映射证据。

## 5. 记进度、共用收尾与常设授权

### 5.1 用户入口和授权

- `$handoff` /「记进度」用于显式交接，以 pause 模式保存当前已授权范围的成果与未完成项；不 push、不建 MR。正常交付无需先执行它。
- 「发起 MR / 创建 MR」或 GitHub 下“发起 PR / 创建 PR”自身授权对当前获授权交付批进行自动收尾、push 与一次 API 创建 MR/PR。条件满足后，同一次用户动作内自动运行 prepare(mr) 和 publish，标题描述自行拟写；不得再要求额外 `$handoff`。已有 MR 或未知外部副作用按 §6.3 只读恢复，不盲重发。
- **记进度 auto-commit** 的路径集恒只含本任务进度文件，落本任务分支。普通成果、当前入口和生成物的范围内 commit 继续由 D-08 承载，不扩大到未知文件、其他任务或 main。交接不是业务冻结，不能借此改写冻结字节或追加未经授权的定稿记录。
- 合并决定恒属 Owner；Owner 核差该批成果、验证、正式裁定、残留及精确清理对象后下达“交付”（含明确执行 $cst-ship / 交付变更），即按 §6.7 委托本批准备、push、创建或识别对象、固定源合并、回读、main 同步和精确清理。仅创建 MR/PR、仅 push 的权限保持；改写历史、其他对象或新批仍另行授权。新会话只读到旧记录不执行，明确“继续交付”才恢复同批剩余动作。

**本批交付条件**：会话核对实际授权、任务类型与本批范围、适用 Verify 结果、冻结/裁定及残留的真实证据。里程碑任务全部验收已满足而无 done 时先停报；未终态任务的合法阶段性 MR 不要求整体任务关闭。代码不能仅凭 caller 自填 true 证明条件，程序核定位与结构、调用方核语义；缺少必需条件不发布，不自行补裁定。

收官次序：终态里程碑任务先由 Owner 判 done，然后核差成果并明确“交付”，由 Agent 按 skill 完成 §6.7 的适用动作；未终态合法阶段批无需整体关闭。仅发起 MR/PR 时保留发布、Owner 合并及按授权整理的窄路径。中途 $handoff 仅保存。上述指令不代替冻结、done、close 或下一业务任务的授权。

### 5.2 准备、提交与失效

会话先核对本批实际需要维护的 current/history/generated 入口，更新当前说明、标明历史时点并按源生成产物。当前入口只写耐久成果和条件化下一步；MR/pipeline 状态、ahead/behind、clean/dirty 由现场读取，不以多份手写快照维护。历史证据不为删除旧状态句而改写；任意散文是否过时由调用方逐处核差，机器检查不声称覆盖所有中文语义。

准备提交关系为：内容提交 C（成果、已核入口、正式记录与证据引用、合法 context 等）→ 单文件追加 handoff 的提交 H。handoff.content_commit 恰为 H 唯一父提交 C；H 的树相对 C 仅修改本任务进度文件且仅追加合法 handoff 行（一条），没有其他路径或既有行变化。H 的 SHA 从文件历史推导，不写回自身。C 可为已有提交；无新增变化且符合本次版本、mode、完整 payload 及引用核验要求的有效 H 已在 HEAD 时，重复 prepare 直接复用，禁止空提交（§6.3）。

有效 H 的 context 必须已在 C 中，source_branch 命中待发布分支，base_commit 可达；entries/evidence 及 §3.2 的建议依据、授权定位均按 C 检查；mr 的源阶段 next 和 after_merge 在同一次准备中核对，二者的授权真实性与对应工作范围由会话核对。合并后仍追溯源提交 H/C 关系，不把 main 的 merge commit 当 H。历史里同一行重复出现或来源不唯一时拒绝猜测。

准备开始前有未知改动、index 中含未声明路径，或要写入他人 worktree 时停报；不得 `git add .` 或自动纳入未声明文件。已获授权的未提交内容以精确路径提交 C，再追加 H。中途 pause 保存未完成内容时如有无法合法入 Git 的敏感材料或暂存产物，只记已核位置与未持久化限制，不能声称它已随交接保存，也不删除该唯一副本。

MR 申报只从最终 H 与本次已核 target/base 生成。完整交付须在 Owner 发指令前完成实质核差；prepare 后复算最终申报，仅允许已核成果及声明的机械交接差异，不一致即停止。准备后任意提交、dirty、输入或生成来源变化，都会使本次发布准备失效；重新核对、准备与生成描述。若 H 已进入 target 且无新交付差异，报告已交付，不建空 MR。合法已审对象发生字节改变时按其治理程序处理，不由 prepare 自动补 Freeze。

### 5.3 合并后的例行整理

完整“交付”中的整理授权与执行条件见 §6.7；以下单独整理仍要求当次精确对象授权。已完成的历史迁移及目录清理不重新触发。

已有本次整理授权时，先核实平台合并事实及实际 source SHA，fetch 后证明 H/C 已进入 target，快进本地 main，核交接与当前材料可读取；逐个核待删 worktree 的 tracked/untracked/ignored 与唯一手工材料，均安全且获点名授权后才 remove、`branch -d` 与 prune。最终核 main、远端目标和所选交接。任何一步不满足，保留现场并报告未达到可直接接力。

正常路径不在 main 补写「已合并」或再创建收据 MR。Lavish/浏览器/poll 不是证据存储；反馈和产物须在删除工作区前有耐久落点。整理不隐含关闭用户会话；不伪称后台监听。只读 check-cleanup 不自行执行 fetch 或删除，它的成功结果只证明本次检查范围，外层整理动作依旧依赖本次授权。

## 6. 现算读取、执行接口与可选核对

### 6.1 读取器

本节为 status/v3 接口；skill 复用现有只读读取器，不新增交付状态计算。

`handoff_status.py [--root <仓根>] [--json] [--resume] [--task <id>]` 是唯一状态读取器，解析仍复用 handoff_lint.py。无 --resume 时保留全仓四段，--task 限定任务简报而不改变跨文件 open/close 集合；--resume 按 §4 选择并验证本次接手，未指定 task 才允许默认选择。

四段语义：等 Owner 拍板 = 未闭合 OD；在办 = 原有任务终态判据与有效上下文、最近过程/交接记录及 Git 位置；刚落地 = 最近五条带有效祖先证明的 result 或 handoff（时间仅用于展示排序，不决定 context 生效）；下一步 = 每个在办任务按 §4.3 选择的当前 next，legacy 标未提供。单独的 resume 简报可包含终态任务。summary 作为交接写入时的声明展示，与现算 next 分开标识；其他活动任务仍保留，不为缩短本任务简报而省略。

JSON schema 为 `handoff-status/v3`。保留 v2 顶层 conclusion/notes/pending_owner/in_progress/landed/next/next_text 及 `resume`（不请求时 null）的键形状；版本升级标识当前 next 的选择语义与原事件版本兼容面改变，不静默沿用 v2 标签。resume 对象闭集字段为 `status`、`task`、`candidates`、`location`、`content_commit`、`handoff_commit`、`next`、`reasons`；status = ready / legacy / ambiguous / unavailable；location = main / source / other-worktree / null。task 未选中为 null，candidates 为任务 id 数组，reasons 为非空原因字符串数组或空数组。resume.next 使用按 §4.3 选中的 §3.2 对象或 null。普通 next 数组每行保留 task/step/text/handoff_next，step 仍为 null；handoff_next 与该任务 resume.next 同义；有效动作的 text 取该对象的 text，显式 none 时 text 为 null，缺少合并后建议时 text 为 §4.3 的缺口说明。resume 在同一缺口下把说明写入 reasons，status 可为 ready；不把建议缺口伪装为证据错误。人读显式 none 显示「本批无后续动作」，不显示字符串 None。

in_progress 保留 context/handoff 解析结果与 location；handoff 为版本化原事件，可为 v1 或 v2，是历史数据而非当前建议接口。消费者只从现算 next/resume.next 取当前建议，不自行读取原 handoff.next 替代。branch 始终表示工作意图，不能把恢复到 main 偷改成 source_branch=main。失败时任何当前建议位置均不残留旧动作；不改变所选失败与其他任务错误分开报告的规则。

0 = PASS（所请求范围算出，--resume 时仅 ready 或已明确选中且祖先核验通过的 legacy）；2 = NOT_CHECKED（缺输入、错误文法/版本、Git 不可用、上下文歧义、证据不可达或材料后继变化未交接）。status 不给 1。每个问题带文件和行/提交定位；另一任务的问题不得伪装为本任务证据错误，全仓视图仍列出其失败，不无声省略。

### 6.2 workflow 命令与本次输入

本节 request/v2 继续作为 prepare/publish 输入；skill 不新增请求格式或恢复参数。

`handoff_workflow.py prepare --request <JSON 文件>`、`publish --request <JSON 文件>`、`check-cleanup --task <id> --source-sha <H>`（另可 --root / --json）为指令内部执行形态。prepare 和 publish 请求 schema = handoff-workflow-request/v2，闭集必填键：`schema`、`task`、`mode`、`paths`、`authority_refs`、`conditions`、`handoff`、`generators`、`mr`。

- paths 为去重的本批精确仓内路径数组，仅含获授权的内容修改路径；不含 H 的自动追加范围，不含未知改动。删除以 Git 记录的原路径明确列出。authority_refs 是非空定位数组，由会话验证工作范围。路径文法沿用 §3.2。
- conditions 是本批交付条件证据对象数组；每项闭集键 `requirement_ref`、`evidence_ref`、`result`。result 为 met / unmet / not-checked；mr 模式 conditions 至少一项、requirement_ref 去重且必需条件只允许 met，pause 保留实际值。条件是否穷尽由调用方依据 Definition/冻结范围核对，程序不能证明漏掉的条件。终态裁定另按 §5.1 原判据核。
- handoff 闭集键为 §3.2 的 summary/evidence/entries/next/after_merge，全部必填；after_merge 按请求 mode 核验。程序生成 version=2、content_commit 与 mode，不允许调用方填写这三项冒充程序生成的 H。generators 为本次已核、可执行的 argv 数组集合；命令必须来自获审入口声明，不能用外来文档充当授权。
- mr 在 pause 为 null；在 mr 模式为包含 title、summary、declarations 的对象。declarations 按 §7 对每个触发路径提供授权与分级等人写申报；字节、冻结行和 diff 从实际 H/base 生成，不信输入数字。缺任一要求字段停报；描述落本地暂存文件供现有平台脚本消费，不进入 Git 形成自指。

启用 request/v2 后，旧 request/v1 与未知 schema 在任何生成、写入或外部操作前拒绝，返回 not-checked / input-invalid 并说明须按 v2 补齐输入；不自动补 after_merge、不退回旧写入。旧事件继续读取不等于旧请求仍可写。

请求文件是单次输入，不是持久化状态正本；只能放布局允许的本地暂存或仓外临时目录，不留唯一证据、不含 token。prepare/publish 完成后的耐久输出为进度文件与 Git，用于恢复正式状态的必要信息必须已进入 C/H；CL-55 切换后完整评审原件按 §7.1 的 EvidenceRef 另读，不复制进交接。运行时源 SHA、目标 SHA、临时描述与进程阶段留在本次调用结果，不新增长期登记本。

publish 必须先调用共用 prepare(mr) 或复用 HEAD 上仍有效且与 v2 请求完全对应的 version 2 H，再生成描述、复核实际远端 source/target、push、一次 create 和 readback。平台按 §6.5 的显式配置选择。GitLab 仍复用本机 gitlab-mr-api，脚本路径由 HANDOFF_GITLAB_MR_SCRIPT 提供；GitHub 通过本机 gh-axi 的 api 调用基本 PR 接口。配置或适配缺失、不满足创建/回读契约时 NOT_CHECKED，不静默换服务器、改全局技能或跳过共用检查。

本机配置只决定如何访问既定仓库，不提供动作授权；origin、配置 project 与目标必须核对一致。配置值和 token 不写入输出或请求文件。prepare 与 publish 的命令、调用方及授权边界通过仓内 AGENTS/HANDOFF 路由，不能由旧全局技能绕开准备直接 push。直接人工 git/API 不在本入口的机械拦截范围，不恢复 hook/CI。

### 6.3 输出、失败与幂等

本节 result/v1 继续作为既有工具输出；skill 分别核对发布之后的合并、同步与清理结果，不将 publish completed 等同整批交付完成。

workflow JSON schema = handoff-workflow-result/v1，字段为 `action`、`status`、`reason`、`task`、`content_commit`、`handoff_commit`、`mr`、`details`。action = prepare / publish / check-cleanup；status = completed / blocked / not-checked / external-unknown。未获得的 SHA、MR 为 null。completed 的 prepare 不表示已发布，check-cleanup 不表示已删除；publish 的 mr 回读对象至少含 id/url/source/target/sha/state。无新差异且已进入目标时允许 completed + reason=already-landed + mr=null，表示未新建 MR，不伪造链接。

退出码：0 = 本动作 completed；1 = 已查明条件不满足 blocked；2 = 未查成或外部副作用不确定。reason 闭集 = none / already-landed / conditions-unmet / scope-mismatch / stale-handoff / evidence-missing / ambiguous-context / input-invalid / tool-unavailable / remote-mismatch / duplicate-mr / external-unknown。details 逐项给证据定位，保留实际失败，不静默降级或吞掉 adapter 的错误。

重复 prepare 的复用条件包含事件 version=2、mode、summary/evidence/entries、顶层 next、after_merge（含 basis_ref）全部相等，以及本次引用和范围核验通过。新增字段不得从比较中省略；无变化不建空提交。C 已有而 H 未落时重新验证后补 H。pause 转 mr、两阶段建议或依据改变、迁移旧 version 1 记录时，不修改旧 H，也不把旧 H 直接标为新版准备完成；以已有 H 或本次合法内容提交为新 C，生成新的 version 2 H。若本批已进入 target 且无新交付差异，仍按 already-landed 返回，不单为接口升级制造空 MR。

在旧版本发布发生外部副作用而结果未知的恢复中，先依据原 source/target/SHA 执行下段 GET 核验，再决定是否有获授权的新交付；不能先改 source H 来绕过原身份查询。新写请求迁移不授权重复 push/create，旧结果可只读核实，追加发布仍需当次授权。

push 成功而 create 未知时返回 external-unknown，停止写操作；后继先调用既有客户端的 GET 能力按 project/source/target/SHA 查询。恰一已有 MR 与全部身份一致且 state 为 opened 或 merged 时报告已有结果，不再 POST；closed 状态、身份不一致或多个命中则 blocked，保留差异。GET 失败不能推断无 MR。只有实际证明无 MR、远端 source 仍为 H、且本次重试已获授权时才允许新的 create；不使用无条件自动重试。原平台脚本的错误处理保持，不换浏览器或实例绕过。

已发布后继续改动需重新准备，追加 push/MR 更新另按当次授权；本批不提供自动 MR 更新或 merge 子命令。目标改变需重算描述和差异，发生分叉、冲突或证据异常原样停报，不自动 rebase/force-push。check-cleanup 要求所给 H 与实际合并 source 匹配且可达；本仓不支持 squash 证据重映射，缺失祖先即停报。

### 6.4 文法核对与实现切换

handoff_lint.py 的 --help/RULES 同步承载 §3 的完整文法，维持 0 PASS / 1 VIOLATION / 2 NOT_CHECKED。status/workflow 共享该解析器和同一计算函数，不自建第二状态读取器。旧六类事件和 context/v1 原文法兼容；handoff/v1 与 handoff/v2 按各自闭集读取，不混用字段，未知版本明确未查成；旧历史不补写、不重新编号。页面与编排调用方必须按 handoff-status/v3 的现算 next 消费，不直接解析新增事件或回退读取原 handoff.next；支持矩阵以实际测试为准。

lint/selftest 不接 pre-commit、gates all 或 CI。workflow 对这次 publish 的交接检查属于已选择动作的前置，不把全仓可选 lint 转回必跑门。设计候选、规则已冻、操作说明或实现已交付、真实客户端已验须分别标明，不由其中一项推导其余项。CL-49/CL-52 的 handoff/v1、request/v1、status/v2 为 CL-53 切换前的历史入口；旧事件按现行文法继续兼容读取，不能据历史说明向当前入口提交旧 request。

CL-53 的实现切换沿革：规则冻结、获授权施工且共享数据校验、lint、status、workflow、相应 selftest 与实际入口适配通过适用检查后，同一交付切换为 handoff/v2 写入、request/v2 输入与 status/v3 输出；切换后拒绝旧请求，保留旧事件读取。HANDOFF/README.md、AGENTS.md、命令帮助及实际调用方继续分别标明规则修订和运行版本。本次 CL-54 不再切换事件、请求或状态接口，也不改变 next 选择算法。

本次 S16 边界须经规则冻结，再经获授权的启动说明与摘要核验实施后，用新的真实会话取得支持证据；不能用候选或先前会话的局部通过替代。支持声明带客户端名称、版本、启动形态和配置身份；CLI print、交互终端及桌面入口分别核验，不相互外推。S16 仍是合并和适用整理后的事后验收，不因待验阻止首次发布，也不因首次发布成功视为 S16 已通过。

### 6.5 GitLab/GitHub 基本发布适配（CL-56）

CL-57 候选（拟 r13，基线 r12）：本节增加独立 GitHub 入口；§6.6 修正首次迁移连接、提交与试批边界。未冻结、未施工前继续使用现行实现。页首既有修订自述为历史，当前冻结事实按治理记录解析。

本节仅在规则冻结、获授权实施并通过本节验收后启用；旧工具仍仅支持 GitLab，不能因候选在场而传入 GitHub 配置。handoff/v2、request/v2、status/v3、workflow-result/v1 的字段闭集和 next 算法保持；mode=mr、请求/结果字段 mr、duplicate-mr 是历史协议名，在已绑定 GitHub 的同次调用中对应 PR，不是第二格式。用户显示名称按平台区分，旧客户端不因字段可解析而获得 GitHub 支持声明。

**本机配置**：GitHub 适配读取 HANDOFF_PLATFORM_CONFIG 指向的仓外 JSON 文件，schema=handoff-platform-config/v1。键闭集为 schema、provider、host、repository、repository_id、target_branch、deployment、deployment_ref。provider=github，host=https://github.com，repository 为 owner/name，repository_id 为十进制正整数的字符串，target_branch=main；deployment=protected 或 private-free，deployment_ref 为仓内当前正式决定的路径与定位。凭据由已配置 gh-axi 环境加载，不入 JSON、不输出。HANDOFF_GITHUB_CLI 可指定本机可执行 gh-axi 的绝对路径，未指定则由 PATH 找 gh-axi；不执行配置中任意 shell 文本。

GitLab 的旧脚本配置方式保留。GitHub origin 而无显式 GitHub 配置时拒绝，不回退 GitLab。若 origin/config/API 仓库 id 不一致、provider 不支持、目标不为 main、归档绑定身份不相容或有冲突配置，返回 remote-mismatch/input-invalid。publish 在任何本地生成/提交及远端写入前核仓库地址、不可变 id 与部署依据；本机配置不构成授权，deployment_ref 须指已生效的实例决定。本次私有免费取值只对经 Owner 明确批准的目标成立，不为下游仓默认放宽保护。

**独立 GitHub 入口**：用户入口名 github-pr-api，仓内脚本为 mechanisms/handoff-protocol/github_pr_api.py；只提供 publish --request <仓外 JSON> [--root <任务 worktree>] [--json] 与帮助。它在任何准备或写入前要求显式 GitHub 配置、拒绝 GitLab 发布配置冲突，然后调用同一个 handoff_workflow.py publish；不复制 prepare、C/H、申报、查重或 API 客户端，不提供直接创建 PR 的旁路。请求/输出沿用 workflow 现行版本与字段；错误仍为同一 result/v1 及退出码。缺配置或错平台明确拒绝，不改环境后重试、不回退旧脚本。既有 gitlab-mr-api 原件保留，GitLab 过渡期回归仍须满足；本项目完成切换后只激活和维护 GitHub 日常发布入口，共用产品适配的兼容契约不由实例迁移自动退役。

**执行接口**：共享 publish 调用同一适配协议 inspect_repository、find_change_requests、read_change_request、create_change_request。身份均绑定 provider/host/repository_id；源/目标只允许本仓分支。GitHub GET /repos/{owner}/{repo} 核 full_name/id/private/default_branch/归档状态/当前权限；GET /repos/{owner}/{repo}/pulls 以 state=all、head=owner:source、base=target 分页穷尽，再逐个 GET PR 核 head.repo.id、base.repo.id、head.ref、base.ref、head.sha。不能只按列表标题、分支名或编号认定同一对象；fork 源拒绝。分页未穷尽返回未查成，不按首屏无结果发起创建。

请求 mr 保持 title/summary/declarations；输出的 mr.id 为项目内 iid/PR number，不是仓库 id；url 为该对象地址；source/target 为短分支名；sha 为 head SHA；state 统一 opened/closed/merged，GitHub closed 必须另核 merged=true 才映射 merged。适配异常无法确认时返回 external-unknown 或 not-checked，不能以 null/false 猜成功。规范化对象供同一 publish/check/read 路径消费，不建立另一个状态读取器。

**写入条件**：先检查本批范围、授权、适用验证、C/H、申报二/三和 §7.1 新增提交，再核实际远端目标/source。目标 main 不存在时拒绝本次日常 publish，指向 §6.6；source 只允许尚不存在或为本次可合法快进的旧位置，分叉不自动修复。push 精确源分支，无 force、mirror 或通配符。创建使用普通 PR，draft=false，不请求付费 Draft PR、自动合并或自动删分支。POST body 为 title/body/head/base；body 使用最终 H 生成的申报，不能省略原申报字段。

无已有对象且远端源精确为 H 时只创建一次；已有 opened/merged 且 H、两端仓身份和分支完全一致时只回读，closed 未 merged、多个命中或身份变化均阻塞。POST 或 push 结果不确定后停止写入，先 GET 和 ls-remote 对账；不自动重试写入。需要再次写入时仍按原协议取得该次动作授权。GitHub 403/404/409/422 不直接等同对象不存在；应分别保留权限/身份/冲突/输入原因，不改投别仓。

**部署边界**：protected 部署要求读回实际生效的主干保护与当前执行身份约束。private-free 部署必须同时满足已生效的 deployment_ref、当前目标私有、已知该目标保护能力不可用；记录明确来源和原因，不把任意查询失败解释成无要求。执行器拒绝 main 直推、强推、自动批准和修改设置；适用 Verify 与显式必要检查仍满足。不宣称拦截其他有写权限客户端；不能实现的服务端原子保护要求仍拒绝。GitHub merge commit 必须可用，squash/rebase 不作证据替代；本批 publish 不执行任何 merge。

**错误与兼容**：沿用 result/v1 reason 闭集，配置错误=input-invalid，身份不符=remote-mismatch，缺适配/不可读=tool-unavailable，业务/保护条件不满足=conditions-unmet，歧义或关闭对象=duplicate-mr，写入未知=external-unknown。details 给具体平台原因与非敏感定位；不得输出 token、含凭据 URL 或原始授权头。旧 GitLab 行为及 fixtures 必须回归；新的 mr 字段解释与客户端显示须同时发布说明。

**切换验收**：P01 两平台身份/缺配置/错项目拒绝；P02 GitHub 普通 PR 创建与完整申报回读；P03 分页查重、fork/多对象/closed 拒绝；P04 push/POST 失联后 GET 对账、无重复写；P05 免费已裁部署与未知 403 区分、main 直推拒绝；P06 GitLab 既有发布回归；P07 人工 merge commit 后 C/H、main first-parent、只读 resume 和按授权 cleanup；P08 新客户端能按平台呈报 PR，旧客户端拒绝未知适配能力。隔离验收与真实平台/新会话验收分别记录，不改 S16 原 NOT_PASSED，也不宣称旧静态 next 缺陷在本批修复。

### 6.6 首次托管历史导入（CL-56）

本节与布局 §7.6 共同规定一次性初始化；不是 publish 的开关，不增加 through-cleanup 授权。候选实施入口为独立 handoff_migration.py check/import/verify --request <仓外 JSON>，尚未实现不得调用。import 只复制已批准的既有 Git refs/对象，不生成业务提交、不修改 origin、不合并、不删除源；切换与归档处理不由 import 暗含执行。

输入 schema=handoff-migration-request/v2；闭集字段 schema、plan_ref、approval_ref、source、target、source_git_url、target_git_url、refs。source_git_url/target_git_url 分别是批准的源/目标 Git 精确地址，独立于对应 host 的 API 根地址；两项与计划逐字相等。plan_ref={commit,path} 指原 GitLab 可达历史中已提交的具体迁移计划，commit 为完整 SHA；approval_ref={commit,path,locator} 指其后 Owner 对该精确计划的批准记录，commit 为完整 SHA、locator 为非空定位；批准记录必须明确指 plan_ref 的提交与路径。两个引用不能相互自指或只指本请求；工具核存在性、源端可达性与计划身份，调用方核真实用户授权。请求中的 source/target/source_git_url/target_git_url/refs 必须逐项等于该计划的批准内容，不能只凭引用存在放行另一个清单。source/target 均为 {provider,host,repository,repository_id}，源=gitlab，目标=github；check/import 均核两端实际 API 身份与 Git 地址，verify 按下述规则只核目标在线身份和本地已批准源证明。refs 为非空去重数组，元素闭集 {ref,oid}：ref 仅完整 refs/heads/ 或 refs/tags/，oid 为精确 Git SHA-1 对象 id，不使用 annotated tag 的 peeled commit 替代标签对象。main 必须在清单内，零 SHA、HEAD、refs/pull、通配符和符号引用拒绝。其他 Git 对象格式本批不支持，拒绝而非截断。

**连接与版本**：source/target 身份仍为四字段闭集；GitHub target.host 只允许 https://github.com。source.host 默认 HTTPS；现有源 API 为 HTTP，不能由源 SSH Git、目标 VPN 或 GitHub SSH 密钥推导其传输已加密。若本次采用 HTTP，精确迁移计划必须明确源身份、实际 HTTP 地址、读取/停写窗口及“HTTP 本身不加密 API 凭据”的事实，由 Owner 对该精确计划的当次批准一并接受；不另建 HTTP 前置批准、source_access 字段或独立批准提交。未有该已提交计划及真实批准前，check/import 不向 HTTP 源发送带凭据 API 请求；verify 不访问源，按下述目标对账规则执行。地址、适用窗口或传输方案改变，重新核差计划与批准；不能自动降级或假称 VPN 已覆盖源。host 不含凭据、路径、query、fragment 或非默认端口。此例外只用于一次性源 API，不扩展 GitHub 或普通发布。

source_git_url/target_git_url 分别只允许无密码的 HTTPS Git 地址、git@host:path.git 或 ssh://git@host/path.git，使用默认端口；主机和去掉 .git 的项目路径必须等于对应身份；check/import 核两端 API 返回的 Git 地址规范身份（GitLab http_url_to_repo/ssh_url_to_repo，GitHub clone_url/ssh_url），verify 只核目标 API 地址，源地址按已批准计划及本地证明读取，不重新声称源 API 当前一致。Git URL 重写后的实际地址须等于批准地址；禁止任意 pushurl、SSH 主机别名重定向、关闭主机密钥核验或自动接受未知主机。SSH 实际主机、密钥身份、服务器主机密钥策略由执行会话核实留证，秘密不入计划；字符串相等不能替代这些事实。GitHub API 继续经 HTTPS gh-axi，GitHub Git 可以用已批准 SSH 地址；SSH 不减免目标空态、精确 refs、atomic 和空期望条件创建。

计划唯一 migration-plan 块使用 handoff-migration-plan/v2，键闭集为 schema、source、target、source_git_url、target_git_url、refs、retained_branch、retained_base、inventory、verification、source_window、writer_exclusion。HTTP 使用说明与实际读取窗口由 source_window 及同件正文承载，批准块仍为 handoff-migration-approval/v1，回指准确 plan_ref 和 action=import；不增第二批准格式。工具先核计划/批准引用、身份和清单绑定，再核相应 action 的平台条件；调用方核真实用户批准及其覆盖的 HTTP 使用说明，非空字符串或伪造批准不能放行。inventory 与 verification 沿现有分类和字段；first_pr 证据须指向点名试批环境与恢复步骤的方案。

新实现仅接受 v2 请求执行 check/import/verify，拒绝 v1 输入且不写入；既有 v1 计划、请求和结果作为历史保存，不自动升级、改旧批准或重试未知写入。此版本变化只涉及独立迁移入口；日常 workflow、handoff 与平台配置版本保持。固定 main 必须具有 v2 规则、适配及适用验收证据，不能只核文件存在就认定具备 v2 能力。

**迁移计划最低内容**：源停写和读取时点、两端身份、精确 refs/对象清单的文件与摘要、在飞内容处置、旧历史/大对象/LFS/子模块盘点、独立档案库与双副本核验、平台协作资产和外部调用方逐项处置、验证/恢复方案、实际允许的初始化动作。固定的 source main 必须已包含本批生效规则及通过验收的必要适配，不能把待审候选当基线。先固定待导入 refs，再提交计划，最后记录对该已提交计划的批准。计划/批准提交不要求反过来包含于它们引用的固定 main，否则会形成提交身份自引用。承载这两项的迁移工作分支必须在计划中列为保留的在飞分支，由原 GitLab 保持可达；首次导入不复制该分支的后续计划/批准提交，目标有基线后通过基本 PR 试批补入，切换前验证这些证明已落目标。最终清单以批准的 plan_ref 为准，导入前任一所选 ref 漂移或出现未申报源内容即停止并重新核差；仅该已申报分支上新增计划/批准记录不改变导入集合，不擅自补范围。

**源保留分支与提交**：retained_base 之后每次提交只允许正式计划或当次批准路径，源保留分支 tip 必须等于批准提交。交接和其他材料须在 retained_base 前保存；源端只按当次点名授权精确 push 批准 tip 并回读，不走会新增 H 的普通 publish，不将该分支先合并进固定 main。导入及 verify 后，在目标首次 PR 试批上下文追加所需交接，源保留分支保持批准 tip；目标新增内容和最终批准链均须另备份恢复。新增其他源 refs 或所选 refs 漂移按原规则重新核差。

**check**：只读核计划/批准、源 API 与清单 ref=oid、对象完整/非浅、目标 ID/私有/主干配置、目标 heads/tags 为空且 API 分支为空。源可达旧 Git 原件按既有 commit 身份保留，不能将任意调用者指定仓外原件加入树；与通常 §7.1 相比，唯一差异是已批准的完整源历史集合不需要预先存在于空目标。需要的历史定位必须在选定 refs 的祖先闭包可达；缺失停报，不能靠保留本机悬空对象称迁移成功。

**import**：再次核 check 输入未变及当次写入授权，排除协作范围内活动写者并明确不能锁住任意远端用户。仅向目标精确 refs 执行原子条件创建：每个 ref 的期望旧值为空，使用显式 --force-with-lease=<ref>: 配合 <oid>:<ref> 及 --atomic。该含 force 的选项只用于“必须尚不存在”的创建条件，不授予覆盖任何已有 ref 的权力；不使用 --mirror、通配符、删除 refspec、自动 fallback 或重写历史。服务端不支持原子推送则拒绝。检查发现目标已有任一 ref 就停止。检查后目标同名 ref 若出现不同 oid，期望空值须拒绝覆盖；若已出现相同 oid，Git 可能返回 up-to-date，不能据此声称是本调用创建。条件约束作用于点名 refs，不能原子锁住整个远端命名空间；并发新增其他 ref 在 verify 检出后阻塞。

**verify / 不确定恢复**：verify 只使用已提交的精确计划、批准、固定源对象的本地完整副本以及目标 API/Git；不初始化 GitLab Adapter、不读取 GitLab 凭据、不访问源 API/refs，不要求 origin 仍指 GitLab。本地核 retained_base 至 approval_ref 的祖先和每提交允许路径等约束，以批准 commit 为边界，不以已追加目标 PR 交接的 HEAD 代替；源实时 tip/refs 与停写事实只由 check/import 在线核验，verify 不报告它们当前仍成立。缺本地批准或源对象即 object-missing，不自动从 GitLab 获取；目标适配仍核显式目标配置、API id 与批准的 Git 地址，在独立迁移验证中不借 origin 选择别仓。

任何写结果未知时停止写入，读回目标全部 heads/tags，与批准清单逐 ref 对账并取得目标对象作 C/H、历史定位与冻结字节验证。import 写后对账也只读目标，不因源随后失联而否定已取得的目标验证结果；写入前的源身份/refs 复核保持。全等且无额外 refs 才能报告 Git 历史内容已核；全等不能证明写入者身份，回读结果与本调用是否创建须分别说明。部分已存在、额外/不同 refs、缺对象、分页/权限失败返回 blocked/not-checked，保留现场，不自动补推、强推或删除。全等恢复不再次 import；证明仍完全为空且授权未失效后，才可按显式继续指令再次尝试。目标已有全等内容不证明协作资料/LFS/归档已迁移。verify 仅验证首次初始化清单；首次 PR 已合法增加分支或推进 main 后，不再用旧清单全等作为最终切换判据，也不删除新增 refs 来使其通过。该阶段按基本 PR 证据、批准的 Git 对象在目标 main 可达、当前冻结对象/历史读取及逐类资料恢复核验，属于正式切换验收。

输出 schema=handoff-migration-result/v2；字段闭集 schema、action、status、reason、plan_ref、source、target、source_git_url、target_git_url、ref_results、details。source_git_url/target_git_url 回显已核无凭据的两端地址；输入不合法时不回显原始 URL。action=check/import/verify；status=completed/blocked/not-checked/external-unknown；reason=none/input-invalid/identity-mismatch/conditions-unmet/target-not-empty/source-changed/object-missing/transport-unavailable/external-unknown；ref_results 为 {ref,expected_oid,observed_oid,state} 数组，observed_oid 未核为 null，state=matched/absent/mismatch/unknown。details 仅非敏感说明与证据定位，不写凭据。退出码0表示该 action 完成，1阻塞，2未查成或外部未知；import completed 不等于平台切换完成。

输入/输出只为当次调用，不是新状态登记本。必要正式迁移决定及结果按已有进度和 Owner Decisions 记录保留，完整资产清单和运行日志按布局 §7.6 保存。不得在 main 补造迁移结果提交、反复创建完成收据 PR 或改旧 handoff。正式切换仍在历史、基本 PR 试批、资产处置和恢复验证后另按具体指令进行，禁止源目标同时作为日常写入口。为解决首次 PR 的 origin 身份检查，导入与 verify 通过后允许当次点名授权的临时试批配置：仍在 D-09 的同一任务 worktree、分支和单一执行会话操作，不新建并行 clone。逐一列出该 clone 的全部 worktree、原 fetch/push URL、目标 origin、原/目标平台配置路径、归档绑定及恢复步骤，核无其他活动写者后，才修改该 clone 共享 origin 与本次进程的显式 GitHub 配置。不得将临时修改伪装为 worktree 私有配置，也不得用 Git 环境覆写或跳过 bind_origin 绕过身份检查。

试批窗口内只有点名的首次 PR 可以向目标写入，源与其他任务停止日常写入；本次进程不设置 HANDOFF_GITLAB_MR_SCRIPT，不删除或更换个人全局脚本、GL_HOST 或凭据。失败或中止先保全目标新增提交/交接与配置现况；push/PR 结果未知时优先保持目标配置，按原请求和实际 source/target/H 身份只读对账，不先 prepare 新 H。已核清结果后，只有恢复动作也已被本次明确授权，才恢复原配置，否则保持停写等待指令。恢复配置不撤销已存在目标 PR、不重试未知创建、不移动 refs。通过人工 merge commit、目标同步及真实新会话只读接手后，另经明确正式切换决定使 GitHub 成为唯一日常入口；临时配置指令不是正式切换或继续其他任务的授权。

验收：I01 空目标正确身份及完整精确清单；I02 检查时非空拒绝、并发同名不同 oid 条件拒绝、同 oid 不冒认本次创建、并发其他 ref 回读阻塞；I03 错源/错目标/源漂移/浅历史/非祖先历史拒绝；I04 旧 Git 报告原提交身份保留，新仓外原件不载入；I05 原子推送失联后的全等、部分、额外 refs 对账；I06 annotated tags/LFS/子模块与外部资产分类，不把 Git refs 等同全部资料；I07 不支持 atomic 时无顺序 fallback；I08 verify 完整历史并验证切换失败时源仍可恢复，固定 refs 后提交计划/批准不形成自引用且首次 PR 补入证明。真实目标动作必须绑定已批准清单，隔离夹具不能代替实际迁移验收。

CL-57 补充验收：v2 两端 SSH/HTTPS Git 与各自 API 身份正确绑定；HTTP 使用范围随精确迁移计划批准，无有效计划/批准时在源 API 调用前拒绝，不能以目标 VPN 事实代替；错主机/项目/API id/重写地址/旧版本拒绝；GitHub SSH 身份、主机密钥和 atomic 能力的真实核验；github-pr-api 与共用 publish 结果及副作用顺序一致；源批准 tip 不被 H 改动；源失联/无源凭据/目标 origin 下 verify 仍可独立对账，源调用计数为零，缺本地证明拒绝且不联网补齐；首次 PR 后按祖先及资料验收、不重复初始化全等核验；临时配置实际影响与未知写入对账后恢复；GitHub-only 环境下发布与只读接手无 GitLab 请求。隔离夹具证明机械拒绝和调用范围，传输、真实首次 PR/人工合并/新会话分别留实测证据；既有 P/I 场景继续适用，不宣称全通过。

### 6.7 cst-ship 交付 skill

Owner 核对本批成果、适用 Verify、正式裁定、残留和指定清理对象后下达“交付”或明确执行 `$cst-ship`，即授权 Agent 完成本批交接准备、发布、固定源合并、回读、main 同步与安全清理。询问、引用和加载 skill 不授权；只推送或只发布保持原范围。既有同批授权沿用，成果或对象变化时先核新差异；不代替 Freeze、done/close 或下一任务决定。

操作指引唯一住 `.agents/skills/cst-ship/SKILL.md`。Agent 复用既有 prepare/publish、archive-v1、Git 和平台客户端，不新增统一 deliver 执行器、交付状态文件或运行协议。handoff/v2、request/v2、status/v3、result/v1 保持；Task 状态单一写者不变。

发布仍按 §5/§6.5/§7 核身份、交接、申报和原件。合并前核实际 PR 源提交、检查与保护，操作绑定已核源 SHA；GitHub 用 merge commit 保留 C/H，不绕过审批、不 squash/rebase。API/Git 回读证明成果进入目标，closed 或源分支消失不能代替合并事实。

同步只快进。清理按本批明确对象核路径、Git 注册、提交与材料，已有 check-cleanup 只证明其检查范围；备份失败或材料未知不删除。当前会话或其他活动会话依赖源 worktree，或依赖无法确认时，保留该目录和本地分支。远端删除绑定预期源 SHA，本地 worktree 不 force、分支只 -d；不全仓 prune、不关闭会话、不为清理建设宿主迁出适配。

取消停止后续写入。明确继续时，Agent 先核原交接、Git、PR 与材料现场，跳过已证实完成的动作；结果未知先查询，输入缺失或范围不能确认则停止，不盲重试或伪造请求。此为 Agent 操作纪律，不承诺通用执行器的任意断点恢复、跨调用严格零写入或并发互斥。

分别报告发布、合并、同步及清理结果。保留工作区时明示清理未完成，不新增完成状态或 main 收据。旧交接建议由调用会话结合当前事实解释，不倒写旧事件或重做已完成动作。实际 skill 验证与支持范围由 HANDOFF/README.md 记载；客户端未验不称支持，Claude Code 验收延期保持。

## 7. MR 描述申报

完整交付时，Owner 在下达“交付”前按本节完成内容、身份、授权和残留核差；最终 C/H 形成后由执行器逐件复算申报与已核内容的一致性，出现新实质差异即停止。单独人工合并仍在合并前核差，工具执行不代替 Owner 终裁。

本节既有 MR 描述名称在 GitHub 对应 PR 描述，申报二/三的标签及逐字段义务保持。首次托管历史导入只按 §6.6 已批准的精确历史范围执行，不通过本节日常 publish 自选基线跳过检查。

MR 描述恒含两项申报（规则正本 = 本节；原「授权登记本机械申报」随三个登记本转只读而无触发对象，自本修订删除）：

**申报二 · 「实质改动 vs 机械证据」构成表**：把本次改动分为实质改动与机械证据两类分别列出，使审阅者不必在证据文件里翻找实质变更。

**申报三 · 受锁冻结件与证据字节改动申报**

- **触发条件**：本次 MR 触碰以下任一路径即须申报：`records/governance/*/freeze-records.jsonl` 各行 `objects[].path` 所列路径；`decisions/**`；`reviews/**`；`records/governance/**`；`tasks/*/reviews/**` 与 `tasks/*/rulings/**`；`.gitlab-ci.yml` 与 mechanisms/gates/hooks/pre-commit（CL-47 已退役的历史触发路径；删除或恢复它们仍触发申报）；三个登记本（`records/evidence-locks.jsonl`、`records/lock-declarations.jsonl`、`records/authorizations.jsonl`，只读历史档案，任何改动即须申报并说明理由）。
- **冻结提交触发条件**：本次 MR 含冻结提交（候选字节 + `records/governance/<subject>/freeze-records.jsonl` 追加行 + `定稿` 指针卷同一提交）时，除逐件申报外，另逐 subject 列出新记录行：`revision`、`event`、`objects[]` 逐件的 `path` / `bytes` / `sha256`，以及该行所在文件与行号；一个变更集含几个 subject 就列几行。
- **申报内容**（逐件一行，不摘要、不改写、不折叠为条数）：
  1. 仓内路径（逐字）
  2. 改动类别：新增 / 修改 / 删除 / 改名（改名逐字写两侧路径）
  3. 该件的现行冻结状态：`freeze-records.jsonl` 内有记录行（逐字抄最后一行 `objects[]` 内该件的条目）/ 只有减重第 2 步前的活跃 `lock`（逐字抄 `records/lock-declarations.jsonl` 该行）/ 无冻结记录 / 历史已退役
  4. 旧字节身份：`bytes` + `sha256`（取 `origin/main` 版本；新增件写 `无`）
  5. 新字节身份：`bytes` + `sha256`（取本 MR head 版本；删除件写 `无`）
  6. 授权依据：Owner 指令原话（逐字）+ 其落点（台账 id 或 `records/governance/<subject>/` 卷路径）
  7. 分级申报：`语义级` / `对齐级`（沿用交付方法 §7.5 二值）；对齐级须附逐处 before / after 表并声明「语义零变化」
  8. 复核命令（供 Owner 逐条粘贴，命令原文；**不得以申报里的数字代替复算**）：
     ```bash
     git diff --stat origin/main...HEAD -- <路径>
     git show origin/main:<路径> | shasum -a 256
     git show HEAD:<路径> | shasum -a 256
     git diff origin/main...HEAD -- <路径>
     git show HEAD:records/governance/<subject>/freeze-records.jsonl | tail -n 1
     ```
- **理由**：`locks` 与 `wiring` 两门自 2026-09-06 退役，受锁冻结件字节、两轴证据登记完备性与提交面 / CI 接线字节已不在任何机械关口的判定面内；现行防线只剩 Owner 合并 MR 时的人工核差，本项申报只让该检查点不漏看、不增加强度。
- **执行与边界**：经 §6 publish 入口时，逐路径必需字段、最终 H/base 的字节身份和冻结记录行由程序生成或核对，缺字段拒绝本次 publish；语义分级、授权真实性和 before/after 解释仍由调用方与 Owner 核差。直接人工 git/API 不受该入口拦截；不接 hook/CI。Owner 仍可用第 8 项命令独立复算，不把机器结构检查称为业务评审 PASS。

### 7.1 评审原件归档后的交接与发布（CL-55 候选）

本节在布局 §7.5 的 archive-v1 切换后适用。handoff/v2、workflow-request/v2、status/v3 的键与 C/H 证明形制不变：evidence 仍是 `{commit,path,locator}`，以固定 Git commit 中的正式 Changelog/ruling/决定及 #review-result 定位结果；旧引用沿原固定来源读取。不得把本机绝对路径填成 Git evidence.path，不得在交接中内嵌任务书、判词、清单、Receipt 或逐轮日志。归档详情由其中 EvidenceRef 按评审通道 §8.6 解析。

普通 status/resume 只验证 Git 交接链、正式结果块及其引用语法，不自动访问归档、不联网、不修复，不把 ready 宣称为原件已核验。默认无归档配置也能读取既有正式决定；下一步若依赖复审、capability 或完整核差，必须在执行前显式读取原件，缺配置、任一副本缺失或内容不符按原未查成/阻塞语义返回。外部 evidence 的权限、真实 verdict 与 Human 处置不由 caller 的自填布尔代替。

prepare(pause) 可保存阶段成果和准确的归档不可用/未持久化限制，不能谎称完整证据已交接。prepare(mr)/publish 对本批正式结果引用调用共享归档 verify，验证所需原件及备份；依赖不可读、伪造最小结果或内容身份不符则阻塞。准备完成后的 C/H、配置、对象、发布来源或引用任一变化使相应验证失效，push 前重新核对实际输入；旧固定 Git 凭据读取不需要把原件复制回 HEAD。

**新增提交检查**是本协议 publish 路径对 FR-50 的实施义务，不接可选 gates/hook/CI：取得本次实际远端目标 ref 的完整 commit，绑定获准推送的 source head 与远端 task branch 原位置；遍历本次将推送且不在已核目标可达历史内的全部 commit/tree/blob。除最终差异，检查每次引入/修改/重命名的对象；先加报告后删除仍拒绝。禁入模式包括根 reviews、tasks/*/reviews、review-attempts、tasks/*/attempts 及 records/diagnostics/review-channel 的完整 Receipt，并用本批及迁移清单中已知原件 bytes/hash 检查改名载入、识别已知完整清单/Receipt 格式。删除已存在于已核目标历史的旧原件合法，不把目标原有 blob 或未修改继承的旧树当本次重新引入。Git 查询失败、目标不可核实或浅历史使范围不完整时返回未查成，不把空集合当通过。

检查结果只保证精确范围、已知内容及格式的可检测性，不能证明任意改写散文或未知压缩格式绝无评审内容。Owner 核差继续检查新文件用途和正式记录最小承载；不自动安装 server/hook，不宣称绕过 publish 的直接 git push 受拦截。对新 task branch 即使远端尚无同名分支，目标分支范围仍要检查；非快进、分叉或未知外部结果按现有停止规则，不自动改写历史。发现本地新提交已包含报告时停止，指出具体 commit/path；移除 HEAD 文件不能解除，改写历史仍需该次 Owner 授权。

申报二继续区分产品与正式治理记录；两轴历史原件删除仍触发申报三。逐件删除身份/授权保持，完整逐轮归档清单和迁移日志仅留仓外，MR 引用正式迁移决定及清单身份，不附原报告。正式切换决定、配置与实现版本须可核，未施工不得以此文档宣称新增检查已存在。

最低新增验收：旧 H/C 与无归档配置的 resume 保持只读；错误 #review-result/跨仓 ArchiveRef/字节不符/备份不可用分别拒绝原件依赖操作；pause 准确保留限制而 mr 阻塞；新增分支、已有远端分支、先加后删、改名、已知原件异路径、旧目标原件合法删除及 Git 查询失败均覆盖。C/H/target/config 同输入复用与输入变化失效分别验证。真实 push/MR 按后续授权执行，隔离预检不算真实发布。

## 8. 与编排者、多 executor 与审阅页反馈队列的接口

- 编排者派发的每个 subagent 恒对应一个任务与一份进度文件；subagent 的结构化结果记录 = 其进度文件的 `result` 行（带 commit 锚），编排者的成果验收读该行、分支上的 commit 与任务实际要求的验证证据；接力读取有效 handoff 与 context，任务终态仍按 §3；可选 lint 没运行时不要求补造结果，不读会话记录或散文推断结论。Owner 拍板项不另立承载面：就是一行 `open · <id> · OD`，其闭合就是一行 `answer`。
- 反馈队列的定向档以任务标识定向（补遗二 §3.3；字面写法沿用该补遗，本设计不转录），任务标识 = 本设计的任务编号，映射唯一；队列本体、常驻服务与消费面不在本设计。
- 编排者看板与桌面客户端页面层的数据源 = `handoff_status.py --json`（补遗二 §4.6 无头调用 + 结构化输出；当前契约见 §6 handoff-status/v3）；页面只取现算 next，不解析进度文件或从原 handoff.next 推当前动作；实际启用按 §6.4。
- 客户端接手摘要与验收报告遵守 §4.2 的同次来源和准确性要求；程序化启动按 §10 S16 记录实际入口与许可，不能把客户端配置当动作授权。状态字段及终态判断仍来自既有正本，不建立独立计数字段、第二份任务状态或通过重写原答复得到的验收结果。

## 9. 只读历史与切换点

- `HANDOFF/journal/*.jsonl`、`HANDOFF/ledger/*.jsonl` 与 `HANDOFF/LEDGER.md` 自旧形制切换点（2026-09-07，r5 的落地提交）起为只读历史：原字节不变、不追加、不重命名；依 repo-layout §7 另行授权后可退出 HEAD，原记录在可达 Git 历史中保留。它们不参与当前状态计算，仅在显式历史条目查询或证据定位时按固定来源读取；只读声明的落点 = `records/README.md`。HANDOFF/status/ 与四个生成物（`STATUS.md`、`PENDING.md`、`OPEN.md`、`CLOSED.md`）随切换点删除，历史版本由 Git 历史承载；r4 引用形态 `journal:<编号>#<seq>` 与 `ledger:<id>` 自切换点起只作历史指针，新行不得使用。
- **切换点转录规则**（Owner 裁定 J3）：切换点仍未闭合的每条开放项在进度文件内各落一行 `open`，沿用原 id（含 `legacy:` 前缀），正文 = 题名 + 一句现状 + 历史指针「（转录自 HANDOFF/…）」（指向 `HANDOFF/ledger/<编号>.jsonl` 或 `HANDOFF/LEDGER.md`，该括注即转录行的机械标记）：每条落其铸造任务的进度文件，铸造任务已终态者亦然（该文件随转录出生，类别行的分支意图写「无（已并入 main）」，并先落一行 `note` 记只读历史层已铸至的编号与新铸起点）；`legacy:` 前缀条目与仓级 `repo:` 前缀条目落 `HANDOFF/progress/repo.md`（仓级写入，Owner 授权动作伴随）。`legacy:` 前缀是 §3 前缀规则的唯一例外，只存在于 `repo.md` 的转录行；含转录行的文件对铸造编号只核严格递增（§6）。转录不改写历史正文，历史正文只在只读层。

### 9.1 历史读取与交接证明（CL-52）

`Repository.file/locate` 与交接核验共用 repo-layout §7.3 读取器；历史查询须显式条目 ID、原路径及可确定的来源，原 `journal:` / `ledger:` 仅在历史引用解析，不恢复为新事件文法。条目定位符必须在所读原件中唯一命中，历史文件存在不等于所引条目存在。当前状态仍仅由当前进度与 ruling 等既有输入计算。

H/C 直接父关系、prepare 的单任务单行追加、后继提交使旧 next 失效等条件保持。context/v1 与退出语义不变；CL-52 形成时保留的 handoff/v1、status JSON v2 是该修订的历史接口，本次 handoff/v2 与 status/v3 的切换及 v1 兼容按 §3.2 / §6.4；entries 声称在 C 的文件仍须在 C 实际存在，不用历史副本填充。已归档原件写入既有 evidence 的 commit + path 引用；不回写旧 handoff，也不把删除之后的提交伪装成原件来源。每个退出批重新生成自己的 C/H。

§7 申报所需的旧 lock 行先按实际目标 base 读取；若登记本已退出，则由该 base 内的有效历史定位选择对应原件，解析既有活跃 lock 分类。trigger 集合保持 §7 原文，不新增 runtime-environment 触发器。旧/新字节身份分别来自实际 base/H 的树，删除侧仍为无，不能从历史补成仍在场；历史只补分类来源。第二批基于已退出登记本的 main 仍须同样正确。

缺来源、冲突或 helper 缺失时，status / resume 保留原拒绝结果并在 reason 说明历史错误；workflow 停在描述/准备的依赖核验，不生成可发布成功结果，错误与退出语义按 §6 原契约。失效的来源不能当作历史任务不存在或完成。CL-52 施工验收新增：固定历史证据恢复成功、来源丢失拒绝；连续两批申报与实际删除身份正确；旧 H 不被改写且后继变化仍使旧 next 失效。

## 10. 最低验收场景

本节为施工验收要求，本次设计冻结不声称这些场景已通过。S16 在真实客户端、真实已交付仓库中按本节细则事后验收；其余场景在隔离 Git 仓内设正例和对应拒绝例。MR 外部调用用可观测替身覆盖调用次数和失败位置，真实平台验证另按授权；隔离替身不代替 S16。

| 场景 | 验证内容 |
|---|---|
| S1 正常 MR 自动交接 | 只给「发起 MR」后先准备 H 再发布，无独立 $handoff；字段缺失或业务条件不足时不发生 push/create |
| S2 中途交接 | pause 保存未完成项且没有网络写调用；v2 after_merge=null；重复无变更无空提交；已有 pause 转 mr 补齐 after_merge 并另生 H，不改旧行 |
| S3 终态与闭合 | done 缺失停报，已有 done 可收尾而不重开；open/answer/close 集合语义、跨任务闭合与原解析回归不变 |
| S4 context 与 KB-28 | 同一任务换分支取最新结构化意图，旧类别行和 note 不改；不从任意自然语言或命名形状生成授权 |
| S5 main 恢复 | H/C 已合入且 source 删除时直接接手；分支消失但证据不可达时拒绝；source 在其他 worktree 时不接管 |
| S6 多任务选择 | main 最近引入边界唯一则选中，多个候选停报；终态任务不从恢复列表丢失，其他工作区零改 |
| S7 后继提交 | HEAD 晚于 H 但只改无关其他任务可恢复；本任务敏感材料及建议依据后继改变无交接则报差异；本任务进度合法 H/answer/close 追加按例外核查；next 不重放已完成 intent |
| S8 准备提交证明 | 验证 C/H 直接父关系、H 单路径单行追加、context 先在 C；伪造父关系、改旧行、未知路径和证据不存在分别拒绝 |
| S9 描述与发布绑定 | 描述只用最终 H/base；prepare 后 dirty/提交/目标改变使准备失效；已合入无差异不建空 MR |
| S10 中断恢复 | C 后中断可补 H，H 后中断可复用；create 未知只读查询，一致已有 MR 不重复 POST，不同身份不更新 |
| S11 当前与历史入口 | 当前运输时点更新/去动态化，历史证据原字节保留，生成源和产物相符，越界 generator 改动停报 |
| S12 输入与版本 | 旧事件兼容；handoff v1/v2 和 context v1 分别核闭集；未知/布尔版本、重复键、控制字符、越界路径和跨任务写入拒绝；命令字符串不会经 shell 展开 |
| S13 输出和检查范围 | status 0/2、lint 0/1/2、workflow 0/1/2 及细分状态一致；未查成不变通过，另一任务错误不冒充本任务失败 |
| S14 整理与唯一材料 | main 已含交接才清理；唯一未入仓反馈、图片或人工材料使清理停报；不关闭 Lavish、不写 main 收据 |
| S15 first-parent 与历史 | fast-forward 和普通 merge 的 H 来源可定位；重复行、浅历史不足、squash 不可达报告限制，不凭树相似映射 |
| S16 真实新会话 | Owner 合并并完成适用授权整理后，在已声明入口及本次完整只读命令许可下，新 Codex/Claude 会话分别仅输入 $resume；按本节细则核原始成果/残留、当前 next 及依据/缺口，不再推荐本批旧合并动作；无补充提示，被测执行主体无写入，宿主独立差异须取证判定 |
| S17 跨阶段建议 | v2 mr 在 source 取顶层 next，普通 merge/fast-forward 后取 after_merge.next；source 删除或保留均正确；v1 任一 mode 与 v2 pause 进入 main 后 next=null 且明确缺口；none 不改变终态 |
| S18 建议与依据 | basis_ref 必填可定位，引用路径列 current；两个 continue-authorized 定位按 C 核；缺依据、歧义来源或未交接变化拒绝；本任务进度具体事件与合法追加不产生自指失效；引用存在不自动授权 |
| S19 准备与迁移 | 新请求 v2 才可写；旧请求在副作用前拒绝；重复比较含 after_merge；旧 H 迁移、pause 转 mr 或建议变化生成新 C/H，旧字节保持；已交付无差异不建空 MR，旧外部未知先按原身份 GET |
| S20 输出一致性 | 普通四段、显式任务、resume、人读和 JSON 的当前 next 一致；main 的后继有效 H 同步更换证明与摘要，未交接更新仍拒绝；summary 标为历史声明，其他活动任务保留；只读运行前后文件/refs 不变、无网络 |

本次规则先按适用修正流程冻结，施工另获授权；首次实现交付在本地适用验收完成后，以已有本批发布授权发起 MR；S16 只能在合并整理后实际完成，是事后接力验收，不是首次创建 MR 的前置。尚未完成时明确待验，不虚报全项通过。该事实可由后继获授权工作按一任务一文件记录，不强迫 main 直接补写或删后再造工作区。

**S16 启动与输入**。验收者在正式会话启动前固定 H/C、仓根、客户端名称与版本、启动形态、配置来源与身份、脱敏 argv、精确权限规则和观察时间范围。日志中的 argv 与配置不得含凭据值。按本次已获授权的验收范围，仅为该进程许可经核对的完整只读命令；需要不同选项、`-C`、组合操作或重定向时逐项核其实际执行及权限匹配，不能用宽命令前缀或整类 Bash 放行代替。禁止通过 bypassPermissions、acceptEdits 或修改全局配置、托管策略实现该验收；未获许可的命令维持原权限控制，配置不生成执行权。

每端必须新建独立会话，不复用或 fork 旧会话历史，文本用户输入恰为 `$resume`，不追加任务编号、答案或修正提示。现有仓级规则、正常技能发现及客户端不含业务答案的启动包装属于已声明入口条件；不得借系统提示或包装注入本次应答结论。先做启动条件预检，再进入正式观测；必要读取被拒而未取得状态时报告启动阻塞，不把进程退出 0 当验收通过。更改许可后须使用新会话 ID，保留原阻塞及其配置，不能在原会话补提示后仍称唯一输入验收。

**S16 事实与来源**。逐端保存原始输入、最终答复、实际工具调用及结果、会话身份与配置身份，按 §4.2 核事实。数量与列举不符、任务/提交/状态或“待验/已验”错误、next 或依据错误均使准确性项不通过，即使正确 next 同时出现也不忽略。检查同一次 status 输出，不以另一次现算替换原答案依据；任意散文的语义仍需人工核差。读取结果未查成时应如实说明缺口，不补造成功。必要原件缺失或关键输出截断而不能完成核查时记未查成，不仅凭摘要重建原答复。

**S16 写入观测**。两端串行执行，避免混合归因；分别保存启动前、会话完成后及已声明宿主收尾范围的文件与 Git 状态。观测覆盖仓内文件、HEAD/index、全部 refs 和 worktree 登记；原始日志由验收者写在被测工作目录外，必要客户端模型连接不等于允许恢复工具联网或执行网络 Git。验收者自身活动与其他会话活动须留痕；存在无法分离的变化时保留差异和限制，不借清理现场重新获得一致快照。

宿主副作用的单独判定同时需要：有宿主日志、调用关联或受控对照证明其由宿主独立维护而非被测会话或工具发起；仓内文件、HEAD/index、分支/tag/远端跟踪引用、worktree 登记及恢复证据均不变；全部实际差异已逐件留证。内部 refs 每项记录前后值、对象类型、与 H 的 tree 关系、时间范围和来源证据；只看 `refs/codex/` 等前缀、tree 相同或没有观察到写命令，均不足以满足来源证明。任何未归因差异继续待核，整体不能无保留通过。已经证明的宿主会话日志、客户端索引或内部观测引用差异可另列为宿主副作用，但不得声称全部 Git 元数据零变化；不允许通过删除、修复或忽略整类引用消除失败。S20 的隔离仓读取器仍须文件/refs 不变、无网络，不能适用此宿主分类来抵销受测工具写入。

**S16 结论与证据保存**。启动、原始答复准确性、交接/next/依据、被测执行主体无写入及宿主差异判定分别有证据，适用项全部满足才可呈报通过；源码回归、旧客户端结果或一次重试成功不能代替其他条件。已证明的宿主副作用与支持入口限制随结论一同披露，未归因或未查成项不得隐去。上述判词是人读验收事实，不新增 status/workflow 的状态枚举或 JSON 字段。按布局已有层次保存关键结论与内容校验基准，原始过程放本地暂存；后继记录遵循一任务一文件和工作分支规则，不为保存结果在 main 补写收据。旧阻塞、失败及会话输出保持；若后继需改判旧结论，须有新证据和 Owner 对该次处置的明确裁定，不能仅因规则修订自动重写。

## 11. 固定边界与残留

不恢复共享 STATUS、历史锁登记、hook/CI 或全局最新任务指针；单写者约束针对各自进度路径。共享 README/生成源发生并行修改时按各自生成规则在任务分支处理冲突并重新准备，不宣称所有文档无冲突。

直接消费者为 AGENTS.md、HANDOFF/README.md、根 README 的源、实际 status 调用方与评审页面；按 §6.4 分阶段对齐，权威指针取各 subject 当前冻结记录，不能将候选修订或未启用接口写成现行事实。CL-49 形成时的其他残留说明（历史）：D-08/D-09 旧节号欠账独立存在，本次不扩大 commit/清理权限；KB-28 只在 S4/S5 验证后关闭；KB-22 仅关闭有证据的子项，KB-30 与产品 harness status 未实现不受该批结论覆盖。各项后继处置按当前进度和治理记录核实，不从本段历史说明重开。

CL-53 的范围为 next 文法、选择与直接消费者；本次 CL-54 只修正 S16 的启动、准确性、写入观测及支持声明边界。既有真实实测的原始阻塞与失败保持，规则修订不直接改判为通过；KB-31 须由适用修复与验收证据处置，不随候选起草或规则冻结关闭。既有完成任务和其他残留按原事实解释；本批不重开原减重第 7 步、迁移或历史退出。

本仓专用规则优先于通用 resume 回退表，但全局技能本体不修改；两客户端实际路由、版本、启动形态和本次配置分别以 S16 验证，未验证的入口不声称支持。整理完成不会自动写入新的接力事实，§4.3 仍只选择既有 after_merge.next；不能以本次验收修正额外引入整理收据或后续任务自动选择。程序只能核结构、路径和 Git 关系，不能证明授权文本来源或任意散文的完备性；这些仍由会话核差和 Owner 终裁。临时材料、后台进程、API 未知结果和不可达历史不得作为已交接的替代证据。
