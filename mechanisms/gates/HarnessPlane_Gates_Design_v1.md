# HarnessPlane Gates 可选一致性工具设计

> Depends on:
> `spec.md@r6 FR-33、FR-34、FR-35`
> `milestones.md@r12 gov-t16`
> `HarnessPlane_Repo_Layout_Design_v1.md`
>
> 权威状态: subject `gates`（治理记录目录按所在仓的布局规则解析；唯一状态正本）

CL-55 候选：拟修订 r18，语义级；原冻结基线 r17。本次仅起草，未送审、未 re-Freeze、未启用。完整变更集见 changelog/CL-55-review-evidence-local-archive.md；当前权威仍按 records/governance/gates/freeze-records.jsonl 解析。

最近已冻结基线（历史）：FROZEN r17，2026-09-08，CL-52 语义级变更集。Owner 已核差通过并授权共同 re-Freeze；冻结事实 = `records/governance/gates/freeze-records.jsonl` 内 revision 17 的记录。本次只冻结规则，历史读取与 HEAD 退出能力仍须完成 repo-layout §7.4 的施工与启用条件，不构成施工或删除授权。

前序冻结（历史）：FROZEN r16，2026-09-08，CL-51 对齐级 amendment。Owner 已核差通过并授权 re-Freeze；冻结事实 = `records/governance/gates/freeze-records.jsonl` 内 `revision 16` 的行。仅对齐已完成的平台退役与验收事实，工具行为、权限与验收判据保持。

前序冻结（历史）：FROZEN r15，2026-09-07，CL-50 第 6b 批语义级 amendment。Owner 已核差通过并授权共同 re-Freeze；冻结事实 = `records/governance/gates/freeze-records.jsonl` 内 `revision 15` 的行。改动范围与已裁例外见 `changelog/CL-50-engineering-documents-and-prototype.md`。

前序冻结（历史）：FROZEN r14，2026-09-07，`changelog/CL-47-optional-governance-lint.md`。Owner 已核差通过、接受本次次序偏离，并授权本变更集 re-Freeze；冻结事实 = `records/governance/gates/freeze-records.jsonl` 内本次 `re-freeze r14` 记录。两份细目设计与摘要数据按原 r13 身份部分退役；gates subject 继续活跃，历史身份由 Git 与原冻结记录保留。

## 1. 目的与边界

CL-56 正式候选：拟修订 r19，原冻结 r18，语义级；起草依据 HANDOFF/progress/repo-od-10.md:668。本文件是 candidate-map.json 指向的正文候选，未生效；现行权威按正式路径及治理记录解析。下方前序候选/冻结说明均按原时点作为沿革读取。

提供人工调用的 layout / manifest 一致性检查与清单生成。目录规则与权威路由仍须遵守；未调用工具时没有检查结果。工具不接本仓 pre-commit 或治理 CI，不改变 Git 权限、Owner 合并权与 Task Definition 要求的产品 Verify 检查。

0 = 通过，1 = 查出违规，2 = 未查成；只报告本次已执行检查的结果，不证明仓库整体合规，也不改变提交或合并权限。

本设计是 gates 单元唯一活设计。布局规则正本 = repo-layout；结果规则 ID 和实际内容核对在 gates_layout.py / gates_manifest.py 声明，不在另一个 JSON 登记本重复抄录。结论契约独立正本已退役，各工具自己的退出码与启动语义由其本地契约承载。

## 2. 调用与输出

```text
python3 -B mechanisms/gates/gates.py all
python3 -B mechanisms/gates/gates.py layout
python3 -B mechanisms/gates/gates.py manifest
python3 -B mechanisms/gates/gates.py manifest --write
python3 -B mechanisms/gates/gates.py selftest
```

可用 `--repo-root <绝对仓根>` 指定检查根，默认从入口位置发现仓根。它服务人工检查与隔离测试，不表示外部可信实现。工作树是唯一内容来源；`--source` 与 doctor 退役，旧参数须报参数错误、退出 2，不能静默忽略。

检查 JSON 写 stdout，人读摘要写 stderr。最小顶层字段为 command、state、exit_code、repo_root、checks；失败原因可附 reason。检查项含 check、state、findings 与 reason，finding 保留 subject（路径）、rule（规则 ID）、detail（原因）。不输出 history_anchor、toolchain、environment、gate_version，不自动落盘。

聚合先判 NOT_CHECKED，否则有 VIOLATION 即违规，否则 PASS。不适用项明示不适用，不把未查成当不适用或通过。规则抛错、缺必要输入、无效 JSON 或 Git 无法查询均保留诊断并给 2。普通读取不写仓库内容。

`manifest --write` 是写入动作，不输出检查 PASS；成功退出 0，失败退出 2，输出已写与未完成路径。参数与字段细则同时见工具 --help。

## 3. 内容规则与真实输入

layout 保留顶层和仓根允许成员、必备与按需目录、sdd 必需规格链与按需 architecture.md、机制单元与设计页首文法、task-id 与证据目录文法、暂存证据不受跟踪规则。CL-47 可选化未改规则 ID；CL-50 将 sdd 规则改名为 `sdd-members`，其必需/可选成员与拒绝条件按布局 §6.1，其他规则 ID 不变。布局未确定的下游安装集合仍报未查成，不猜测合法成员。

Git tracked 路径是 staging-not-tracked 等内容检查的必要输入；取消 index 内容快照不取消该查询。必要路径查询须固定影响枚举的 Git 配置（core.ignoreCase=false、core.precomposeUnicode=false），不恢复工具链身份摘要。Git 错误不得当空集合，已跟踪的 tasks/*/attempts/ 仍应查出。浅克隆不再仅因历史不完整拒绝内容核对。

rules_catalog.json 保留实际仓型集合与 generated 描述，top_level_members 和 root_tracked_members 继续被 review-channel 读取；缺任一必需键仍使通道 preflight 拒绝。删去没有消费者的 must_lock_extra、wiring_targets、managed_regions 与重复规则登记，不改变保留集合的布局语义。

## 4. 清单生成与写入

根 README 与 mechanisms/MECHANISMS 是整文件生成物，不手改。叙述源保持 root_readme_source.md / mechanisms_source.md，数据源保持 readme_data.json；磁盘发现集合参与输出。manifest 比较现有文件与生成结果，遗漏、数据不完整或内容过期报告具体差异。

机制单元清单从磁盘单元目录发现；subject 花名册的现存列从单元名及已出生证据 / 治理目录派生。另从工作树 `records/history-locations.jsonl` 的 roots/paths 提取显式历史定位声明，分列标注“历史定位声明（未核验历史对象）”，不声称该目录当前存在，也不证明完整产品 subject 集合。历史声明不改变现存集合的完备性检查。

先算完全部输出再写入，拒绝符号链接目标，逐文件原子替换。多文件不是事务：第二文件失败时准确报告先前成功文件与未完成文件，不声称全部回滚，允许修复后重跑。同输入连续生成须字节相同。

设计摘要生成链无下游消费者，已退役 design_summary_catalog.json、受管区标记与其读写路径；不得删除其数据但留下无条件前置检查。gates subject 仍活跃，部分退役对象不再加入 r14 活对象。

### 4.1 历史定位声明的生成边界（CL-52）

只调用 repo-layout 共同 helper 的 `validate_locations_syntax`，不解析 source_commit 的树、不读取历史 blob、不验证来源可达、摘要或只追加沿革；这些保证归显式 history_read check。缺定位文件的工作树不增加历史声明，是否曾启用不由 manifest 查询 Git 历史。文件在场但语法错误、依赖 helper 缺失按必要输入未查成处理，退出 2；manifest --write 在生成完成前拒绝，不写部分错误内容。

声明的 subject 只从 roots/paths 中直接包含的 `reviews/<subject>/` 或 `records/governance/<subject>/` 前缀识别，按现有 subject 文法校验。宽根如 `reviews/` 不枚举历史 subject，tasks 轴不强转为机制 subject；exclude 不用于推断剩余历史文件。该列仅说明显式定位前缀，不声称退出范围非空或文件有效；不捏造目录链接，给出原路径与 source_commit 的读取说明。同输入生成保持确定性。rules_catalog.json 及既有规则 ID、两个 root closure 键保持。

施工验收须覆盖：退出 subject 仍有声明、现存目录不被历史充数、宽根不猜 subject、坏 JSON / 缺 helper 退出 2、有效浅克隆仍能生成、全程零历史对象读取、生成连续两次相同。设计冻结不表示生成器已切换；按 repo-layout §7.4 完成施工前，入口只声明尚未启用。

### 4.2 CL-55 归档切换后的内容与清单

layout 在 archive-v1 模式按布局 §7.5 拒绝新完整评审原件受跟踪，包括两轴 reviews 和能力 diagnostics Receipt；迁移批中尚未退役的旧 tracked 原件只能按切换决定中的精确 legacy 来源核对，不默许新字节。review-attempts/tasks/*/attempts 继续永不入 Git。模式和正式决定不一致时不能以 legacy 默认掩盖已切换事实；layout 只核当前内容，全部新增历史检查归 handoff publish，不把此工具包装成提交硬门。

manifest 保持工作树纯生成，不读取本机归档配置、inventory、对象或完整 Git 历史。现存单元与正式治理目录继续派生 subject，旧 history-locations 的显式声明沿 §4.1；没有该类声明的私人归档 subject 不在花名册虚构补齐。空 reviews 目录不是丢失治理事实的证据，生成物不创建私人绝对路径链接。根 allowed 集合保留 legacy 名字供旧来源解析，rules_catalog.json 本次字节不改。

新增验收：迁移后根/任务 reviews 不存在仍能生成；缺本机配置且当前正式记录可读时 manifest 可运行，layout 的切换状态缺证据则明确未查成；新 tracked 报告/diagnostics Receipt 拒绝，旧原件精确匹配例外与被改字节分开；连续生成稳定、只改叙述源而未生成仍报告过期。

## 5. 消费者与平台迁移

review-channel 保留自己的净化启动、gates.interpreter、Receipt、五题和两个 catalog 键。handoff status / lint 与 artifact lint 自己承载原有返回语义，不继承不同工具的成功定义。

CL-47 已删除治理 CI 文件与受跟踪 pre-commit hook；2026-09-07 平台执行记录确认项目成功 pipeline 必需条件取消、Auto DevOps 有效 false，本项目 PINNED_CI 自定义治理绑定整体退役。执行事实、证据来源与该自定义机制维护义务的退役边界见 `records/GITLAB_CI_ENFORCEMENT.md`；GitLab 部署期间原配置、权限与 main 保护继续适用；GitHub 私有免费部署的协作/执行器边界按交付方法 §6.4 和交接协议 §6.5 的显式实例决定解析。gates 不模拟服务端保护，不恢复 hook/CI，也不由其通过替代迁移验收。仓内文件删除不证明服务器已变；未完成或另一次平台变更仍须该次动作授权与实际回读，不能凭仓内结果声称实际 MR 不受治理 pipeline 阻断。

不更改用户全局 Git 配置；不要求 clone 安装 lint hook。评审通道的仓库本地解释器配置仍须保留，不能因同名 gates 前缀而删除。

## 6. 反思

自动关口退出后的变化是没有自动布局 / 清单检查。保留工具能力不恢复该保证，人读 MR 核差也不冒充机械检查。最终候选与冻结记录同次提交才能使文档、代码和记录身份对应；本次 CL-52 冻结状态由对应记录与定稿指针的共同提交成立，历史读取能力仍待施工与启用验收。

保留生成链因为已有真实消费者；保留 tracked 路径因为具体规则仍读它；保留 --repo-root 因隔离验收仍需要明确检查根。只移除无消费者的运行时身份、全历史、索引、设计摘要及扩展框架。

## 7. Rejected alternatives

- 恒绿作业、吞掉 lint 错误或 allow_failure 代替退出接线：保留伪通过界面，不符合真实结果要求。
- 删除整份 rules_catalog 或清单生成链：会破坏评审通道及现有清单用户；K2 明确保留生成链。
- 因为没有 index 而删 Git 跟踪核对：遗漏已跟踪暂存证据，削弱仍有效规则。
- 把每次 MR 人工 lint 写成必跑清单：重建已取消的强制流程。
- 单纯把工具改名或把 --source 忽略：制造第二入口或让旧调用静默改变语义。

## 8. 最低验收场景

- 人工制造独立布局违规，layout / all 退出 1且规则与路径可见；隔离 clone 的普通 commit 无 --no-verify 仍成功、未执行本仓 lint。
- 缺件、坏 JSON、Git 失败与实际未查成退出 2；聚合不掩盖失败。有效内容退出 0。
- 改源不生成时 manifest 退出 1，生成后通过；同输入连续生成字节一致，符号链接目标与写失败有真实诊断。
- 工作树变化可见，受跟踪 attempts 报违规，浅克隆可核对，旧 --source 退出 2。
- 每个保留内容规则有有效正负例；去掉关键检查可被测试发现。selftest 仅写隔离临时仓，普通读取无副产物。
- review-channel root closure 的两个键各自缺失均拒绝，正确输入通过；启动和退出语义不变，无 provider 调用。
- 平台验收判据保持：平台变更按授权完成并回读后，实际 MR 不因缺治理 pipeline 阻断。CL-47 的 V9 已完成，其当次 MR !103 回读与验收事实见 `HANDOFF/progress/repo-od-10.md` 的 2026-09-07T07:26-07:00 `optional-lint-platform-execution 后继运输验收` note；该记录不证明未来平台状态，本次文档核对也不替代真实平台或 MR 验收。
