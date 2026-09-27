# CL-57 GitHub 发布与首次迁移工具

## 本项目的正式 GitHub 入口

本项目按 [handoff-protocol-D16](../../records/governance/handoff-protocol/HarnessPlane_Handoff_Protocol_Owner_Decisions_D16.md) 切换至唯一活动仓库 <owner>/<repo>，决定随本批进入 main 生效。origin fetch/push 为 git@github.com:<owner>/<repo>.git；本机配置路径及摘要、归档读取和最终完成判据见 [切换记录](../../records/diagnostics/github-first-migration/2026-09-10/cutover.md)。新会话显式加载配置，不修改全局 shell/个人技能；配置不赋予下一次发布授权。

已获本次发布授权并形成仓外请求后，在相应任务 worktree 调用：

```sh
env -u HANDOFF_GITLAB_MR_SCRIPT \
  HANDOFF_PLATFORM_CONFIG=<平台配置 JSON 的绝对路径> \
  HANDOFF_GITHUB_CLI=<GitHub CLI 程序 gh-axi 的绝对路径> \
  python3 -B mechanisms/handoff-protocol/github_pr_api.py publish \
  --request <本次已核仓外请求绝对路径> --json
```

本项目后续不运行 GitLab 发布或一次性导入命令。下文一次性迁移说明用于已批准迁移的历史解释及工具适用边界；既有源 HTTP 窗口不构成新的源访问授权。已验 Codex CLI 接手、延期 Claude 验收及原 S16 保留范围见切换记录。

本件规则已随 CL-57 冻结并获授权实施。独立迁移 request/plan/result 已使用 v2，github_pr_api.py 已接入共用发布；CL-56/CL-57 的历史施工验证及完整候选索引已退出 HEAD，按 [诊断历史读取](../../records/README.md#诊断历史读取) 从固定来源读取 `implementation-validation.md` 与 `candidate-map.json`，原件仅说明形成时的验收范围。正式切换及最终完成读取使用本件页首切换记录。CL-56 运行说明保留于固定提交 0f149c7503b21a98981ac91634b9ebaa796e27d1 的同路径，可用 `git show 0f149c7503b21a98981ac91634b9ebaa796e27d1:mechanisms/handoff-protocol/MIGRATION.md` 读取。正式规则为交接协议 §6.5/§6.6 与布局 §7.6。

## cst-ship 简化边界

迁移与 PR #3 目录整理按已完成事实读取，不重新导入。cst-ship 简化为 Agent 使用已有工具的操作指引，既有 github-pr-api 继续只发布，原请求/结果格式保持；不新增共享 deliver。规则生效和真实支持范围见 HANDOFF/README.md，Claude Code 验收继续延期。

## GitHub 发布

独立入口 github-pr-api 对应 mechanisms/handoff-protocol/github_pr_api.py，只接受 publish --request <仓外 JSON> [--root <任务 worktree>] [--json]。进入同一个 handoff_workflow.py publish；无独立 prepare 状态、无裸 POST、无 merge/cleanup。使用现有 HANDOFF_PLATFORM_CONFIG 与 HANDOFF_GITHUB_CLI，缺 GitHub 配置、GitLab 配置冲突、origin/API 身份不符即在本地生成/提交和远端写入之前拒绝。现有 workflow/request/v2、handoff/v2、status/v3 和 workflow-result/v1 保持；无新 token 变量，不改 GL_HOST 或个人脚本。

## 一次性迁移

输入 handoff-migration-request/v2，闭集 schema、plan_ref、approval_ref、source、target、source_git_url、target_git_url、refs。source/target 仍为四字段身份；source_git_url/target_git_url 为各自精确 HTTPS 或 SSH Git 地址，host 是各自 API 根地址。GitHub API 始终 HTTPS，目标 Git 拟用 git@github.com:<owner>/<repo>.git；源 HTTP 的地址、窗口与未加密凭据事实写入精确计划，由当次计划批准一并接受，不另建前置批准或 source_access 字段。目标 VPN 或 SSH 不证明源 HTTP 加密。Git 地址须同项目、同主机且与 API 声明及最终实际地址一致，不能用 URL 重写或 host 别名规避。

唯一 migration-plan 块为 handoff-migration-plan/v2，闭集及 HTTP 使用说明以协议 §6.6 为准；approval/v1 继续回指真实 plan_ref。v2 工具拒绝旧 v1 运行请求，不自动升级批准或重试。输出 handoff-migration-result/v2 增 source_git_url/target_git_url，其余 action/status/reason/ref_results 和退出码语义保持；未知版本消费者必须拒绝，不解析成已完成。

check/import/verify 仍在 handoff_migration.py，分别绑定同一仓外请求；本说明不提供含占位身份的可运行 JSON。固定 main 先接纳必要规则和实现，库存/交接先固定 retained_base，再提交精确计划和后继批准。源保留分支精确 push 至批准提交，不经过普通 publish 或预先合并源 main。import 保持一次精确 atomic 空期望创建，无 mirror、覆盖、删除或 fallback；verify 用已批准计划/批准及本地固定源对象，仅访问目标 API/Git，不加载源适配或凭据；源实时 refs 检查仅用于 check/import。缺本地证明拒绝，不回源补取。import 写后同样只对账目标；源失联不能阻断目标核验。

## 首次 PR、最终切换及恢复

导入/verify 通过后，由当次试批指令点名任务 worktree、分支、同一 clone 全部 worktree、原 fetch/push URL、目标 origin、平台配置及归档绑定，核无其他写者，保存非敏感配置备份；授权须明确试批失败时是否允许恢复原配置。然后临时切换共享 origin 与当前进程 GitHub 配置，保持同一任务/分支/写者，运行独立入口的共用发布。源端保留批准 tip，不再推回目标试批新增 H。禁止环境覆写绕过 reader 身份检查，禁止另开并行 clone。

失败先保存新增内容与配置；未知 push/PR 优先保持目标配置，以原请求/source/target/H 只读对账，不先 prepare 新 H。结果已核清后，再按已获授权的恢复动作执行；没有恢复授权则保持停写，不改 refs、不撤销目标 PR、不重试未知创建。成功后核人工 merge commit、同步与真实新会话，最终另经明确切换使 GitHub 为唯一日常平台。切换前须完成主仓最终备份、MR 遗漏对象、独立档案库、协作正文/附件/CI 和评审双副本恢复；拒绝 GitLab 访问后验证必要读取、发布和接手。服务关闭、删仓、撤销凭据都不是 import 的副作用。

初始化 verify 只接受原精确清单全等。首次 PR 合法新增 refs/推进 main 后，正式切换核验改按 PR 合并证据、旧对象在目标 main 的祖先关系与资料恢复，不重跑初始化全等来否定合法变化，也不删新 refs。

## 本机调用与限制

以下命令只描述入口；发布、精确 import、临时配置和正式切换仍各依当次授权。请求文件使用已核的绝对仓外路径。

```text
python3 -B mechanisms/handoff-protocol/github_pr_api.py publish --request <仓外请求> --root <任务worktree> --json
python3 -B mechanisms/handoff-protocol/handoff_migration.py check --request <仓外请求> --root <任务worktree> --json
python3 -B mechanisms/handoff-protocol/handoff_migration.py import --request <仓外请求> --root <任务worktree> --json
python3 -B mechanisms/handoff-protocol/handoff_migration.py verify --request <仓外请求> --root <任务worktree> --json
```

HTTP 精确计划须在 source_window 给出真实读取/停写窗口，并在该字段或同件正文包含明确说明“HTTP 本身不加密 API 凭据”；计划绑定实际源 HTTP 地址。工具检查此说明和已提交批准块，执行会话仍须核真实 Owner 指令及覆盖范围，不能用文字或自行写入的批准替代授权。旧 v1 请求在任何平台构造和写入前拒绝，不自动转换旧计划。

迁移 SSH 采用调用级 BatchMode=yes、StrictHostKeyChecking=yes、UpdateHostKeys=no，关闭复用旧 SSH 连接与自动主机名转换，显式使用默认 SSH 端口。每次传输前只读检查 Git URL 重写及 ssh -G 的实际 hostname/user/port/hostkeyalias；不修改本机配置、known_hosts 或 ssh-agent，不接受未知主机密钥。Git 的 core.sshCommand 在本次进程中固定为上述 OpenSSH 调用，用户的 GIT_* 覆写不继承；这是迁移传输约束，不改变 origin，也不用于绕过发布身份检查。实际服务器身份与密钥权限仍须当次独立验收，代理等本机配置的实际路线由执行会话核实。

verify 只使用已批准本地证明与目标配置，不需要 GL_* 或 HANDOFF_GITLAB_MR_SCRIPT。缺 Git 对象使用 cat-file 核实并报告 object-missing；不从源补取。import 写后任何对账异常报告 external-unknown，停止写入并保留目标。源 refs/tip 的当前事实只由 check/import 写前重新核实。
