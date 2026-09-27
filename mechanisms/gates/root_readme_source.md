# csthink-harness-plane

HarnessPlane 融合产品线的唯一交付仓：受治理的 Git 仓库 + 可执行门 + 编排 CLI + 现成 Coding Agent + Owner 裁定——治理机制本身即产品。

本文件**只指路**。规则与语义以各自正本为准，冲突时以正本为准。协作契约：`AGENTS.md`。物理布局权威：`mechanisms/repo-layout/HarnessPlane_Repo_Layout_Design_v1.md`。

## 仓库地图

下表由磁盘发现的顶层目录派生（`manifest --write` 生成；核对 = 人工可选 `manifest`）；列值正本 = `mechanisms/gates/readme_data.json`。

<!--table:top_level_map-->

可选顶层目录按实际需要建立（just-in-time），到第一件真实内容落地时才建、不预建空壳：`.claude/`（适配层，gov-t14）、`apps/`（产品源码区）、`authority/`（重立权威件）、`ui/`（UI design lineage）、`review-attempts/`（本地暂存，永不入 git）。三区语义与各目录边界见布局权威。

## 概念路由

| 我要找 | 去哪 |
|---|---|
| 产品要解决什么、范围、约束与验收条件 | `sdd/spec.md` |
| 提案背景、四段旅程与交付形态 | `sdd/proposal.md` |
| 新建/存量项目接入、正式 feature 来源与成功条件 | `sdd/spec.md`（FR-18、FR-57/58/59、SC-3/SC-9）；交付顺序与边界见 `mechanisms/delivery-method/HarnessPlane_Delivery_Method_Design_v1.md` §5/§6.1 |
| 做什么、什么顺序、任务身份与依赖 | `sdd/milestones.md` |
| Assistant 联合计划、固定输入与对接接收条件 | `records/diagnostics/assistant-hp/2026-09-21/README.md`（原文副本、来源身份、适用性和 J-01 接收边界） |
| proposal / spec / milestones 三类工件怎么写、可选核对怎么跑 | `mechanisms/artifact-templates/`（生命周期工件模板 + `artifact_lint.py`，`--help` 承载规则原文；不接线） |
| 变更设计怎么写与何时需要 | `mechanisms/artifact-templates/design.template.md`（人工核对骨架）；交付方法 §6.2（适用条件与核差）；台账任务用合法诊断规划 |
| 产品级架构说明 | 按需 `sdd/architecture.md`（非冻结工程说明，不作规范性权威；未建立时无文件）；布局 §6.1 与交付方法 §4 |
| Task Definition、task record、ruling 怎么写；legacy-v0 与仓内 done 如何解析 | `mechanisms/artifact-templates/task.template.md`、`mechanisms/artifact-templates/ruling.template.md`（形制）；`tasks/README.md`（生命周期三句与 legacy-v0 解析） |
| 某个产物该放哪 / 目录边界 / 仓根闭集 / 证据分层 / 载荷边界 | `mechanisms/repo-layout/HarnessPlane_Repo_Layout_Design_v1.md` |
| Stage 0 至 Stage 3 交付方法、修正语义与评审插件矩阵 | `mechanisms/delivery-method/HarnessPlane_Delivery_Method_Design_v1.md` |
| Stage 3 任务工作流拓扑 | `mechanisms/delivery-method/MVP_Workflow_v5.drawio` |
| 可选一致性检查的语义与命令 | 本文件「可选 lint 与命令」核心句；mechanisms/gates/HarnessPlane_Gates_Design_v1.md 与工具 --help |
| layout / manifest 的设计、规则来源与 selftest | `mechanisms/gates/HarnessPlane_Gates_Design_v1.md`（现行冻结事实按 `records/README.md` 解析 `records/governance/gates/freeze-records.jsonl`） |
| 创始产物是谁评审、谁批准、依据什么 | [创始出处历史读取](records/README.md#创始出处历史读取) |
| 有哪些机制单元、哪些进分发载荷 | `mechanisms/MECHANISMS.md` |
| 本仓怎么协作、什么动作需要授权 | `AGENTS.md` |
| 接手、记进度、MR/PR 申报与托管迁移前置怎么走 | `HANDOFF/README.md`（指针与操作摘要；申报规则正本 = handoff-protocol 设计 §7） |
| GitHub 独立 PR 入口与首次迁移工具怎么用 | `mechanisms/handoff-protocol/MIGRATION.md`（github_pr_api.py 与 handoff_migration.py；连接配置不授予发布或迁移权限） |
| 本项目治理 CI 服务端机制的退役记录与仓外历史 | `records/GITLAB_CI_ENFORCEMENT.md` |

CL-55 已按 records/governance/review-channel/HarnessPlane_Review_Channel_Owner_Decisions_D11.md 启用 archive-v1，本任务分支的 reviews/ 与 tasks/*/reviews/ 原件已迁移退出。新轮使用仓外双副本，正式结果留在 Git；固定旧轮来源由切换决定与既有历史声明解析。主 checkout 与远端是否已交付须按实际合并状态核实，不能从旧版本发起新评审。

## 证据布局与 subject 花名册

去哪找证据（规则见布局权威 §3.2 与 §7，本节不复述）：

| 找什么 | 去哪 |
|---|---|
| 某个对象 / 单元的评审证据 | 按正式决定的 EvidenceRef 读取；旧逻辑路径 `reviews/<subject>/<round>/` 由固定来源解析 |
| 某个任务的评审证据 | 按 ruling 的 EvidenceRef 或原固定来源读取；旧逻辑路径 `tasks/<task-id>/reviews/` |
| 某个 subject 的治理记录（Owner 裁定与定稿记录） | `records/governance/<subject>/` |
| 过程性原始材料（不入 git） | `review-attempts/`、`tasks/*/attempts/` |

subject 花名册（subject 名 = 对象 / 单元名，落点由名字派生）。本表的现存项由机制单元名与已出生证据目录名派生。历史定位文法与启用条件见 repo-layout 设计 §7；历史声明与现存目录必须区分，生成器按 gates §4.1 增加历史声明列，只校验工作树声明语法，不查询历史对象。该列不证明历史对象可达，本表不证明完整产品 subject 集合。

<!--table:subject_roster-->

**两轴分流**：以下物理目录为 legacy-git，归档后只保留原逻辑身份，不再创建新轮目录。subject 轴旧逻辑路径为 `reviews/<subject>/`，任务轴旧逻辑路径为 `tasks/<task-id>/reviews/`；同一 subject 可只在其中一轴有证据。创始产物的逐件指针按 [创始出处历史读取](records/README.md#创始出处历史读取) 获取。

## 可选 lint 与命令

CL-47 已冻结 layout / manifest 的人工可选调用形态；平台退役事实与历史见 [平台记录](records/GITLAB_CI_ENFORCEMENT.md)，权限边界见 `AGENTS.md` §6。是否已并入 main 按现场 Git 核实。

0 = 通过，1 = 查出违规，2 = 未查成；只报告本次已执行检查的结果，不证明仓库整体合规，也不改变提交或合并权限。

```text
python3 -B mechanisms/gates/gates.py all
python3 -B mechanisms/gates/gates.py layout
python3 -B mechanisms/gates/gates.py manifest
python3 -B mechanisms/gates/gates.py manifest --write
python3 -B mechanisms/gates/gates.py selftest
```

可选 `--repo-root <绝对仓根>`；唯一内容来源为工作树，旧 --source 参数与 doctor 已退役。JSON 写 stdout，人读摘要写 stderr；结果不自动落盘。manifest --write 只报告写入结果，不给检查通过结论。selftest 人工发起，在隔离临时仓运行。

根 README 与 mechanisms/MECHANISMS 是整文件生成物，不手改；改 gates 下的叙述源或数据后显式运行 manifest --write。漏生成可在人工核对时发现，不自动阻断 commit。Task Definition 要求的适用产品 Verify 检查仍须执行，FAIL 不可伪装 PASS。

三个登记本与 runtime-environment 为只读历史，冻结件字节与证据完备性由 MR 申报和 Owner 人工核差承载，见 HANDOFF/README.md 与 records/README.md。规划基线修正提醒器在 mechanisms/delivery-method/run_delivery_method_reminder.py，按交付方法规定运行。

## 冻结怎么做（减重第 2 步起）

候选字节 + `records/governance/<subject>/freeze-records.jsonl` 追加一行 JSON 记录 + `定稿` 指针卷，**一次提交**落地；记录行文法的正本 = `mechanisms/freeze-record/HarnessPlane_Freeze_Record_Design_v1.md`，现行冻结事实的解析规则 = `records/README.md`。MR 描述含申报三（逐 subject 列出新记录行，形制见 `HANDOFF/README.md`）；Owner 按交接协议 §7 在完整交付指令前或单独人工合并前核差。两提交仪式、`cst-freeze` 工具与三个登记本已退役。

## 评审通道解释器配置

人工 lint 无 hook 安装前置。评审通道自己的净化启动仍要求仓库本地解释器配置，绝对路径由用户给出：

```text
git config gates.interpreter <本机解释器的绝对路径>
"$(git config --get gates.interpreter)" -B -E -s -S -X pycache_prefix="$(mktemp -d)" mechanisms/review-channel/review_channel.py <子命令> [选项]
```

该配置只服务评审通道，不设置全局配置，不要求 core.hooksPath。调用与退出语义以评审通道设计 §5.3 为准，review 的退出 0 可承载 PASS 或 FAIL 判词。

## 出生态

本仓由 gov-t1 出生：骨架、创始三实例（以终名落位、字节等于出生档案库的现行生效版）、创始出处清单与布局权威落位。
gov-t3 重生的交付方法单元已落位，包含设计正本、方法全图、Stage 3 拓扑源文件、机械提醒器与 selftest。
创始过渡态的出生历史与已知边界由创始出处清单历史原件承载，读取见 [创始出处历史读取](records/README.md#创始出处历史读取)；创始 proposal、spec 与 milestones 已分别随 gov-t19、gov-t20、gov-t21 按各自当时的物理 schema 对齐，并由本仓治理链唯一解析其现行状态；该三份 schema 设计正本已随减重第 5 步退役并合并为 `mechanisms/artifact-templates/` 模板集，正文中仍保留的历史引用只按当前内容与对应模板解释，不再作为待对齐状态。
task 物理 schema 曾以 `task-artifact-schema` FROZEN r1 / r2 在本仓建立，已随减重第 5 步退役（`changelog/CL-45-artifact-templates-and-schema-retirement.md`）；现行 task record 形制 = `mechanisms/artifact-templates/task.template.md` 与 `ruling.template.md`；自举期 task 树由 accepted legacy-v0 inventory、追加式 redefinition / ruling / review evidence 与 Git history 统一解析（规则 = `tasks/README.md`）。

历史证据按需读取的文法与启用条件见 mechanisms/repo-layout/HarnessPlane_Repo_Layout_Design_v1.md §7，各消费者保持自身状态权威。CL-52 读取器与消费者施工验收按 [诊断历史读取](records/README.md#诊断历史读取) 获取 history-retention-implementation-validation.md 原件；实际退出仍须逐组核依赖与来源并取得 Owner 点名授权。

## cst-ship 统一交付

当批“交付”的权限与材料规则见 handoff-protocol §5/§6.7；cst-ship 为 Agent 组织已有工具的操作指引，实际入口与支持范围见 HANDOFF/README.md。现有 github-pr-api/publish 保持窄发布，不引入额外交付执行器或状态协议。
