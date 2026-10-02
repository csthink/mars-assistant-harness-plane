# Harness Runtime Contract adapter, task acceptance, Workflow progression, Policy Gate and the Definition loop

这里是 feature-t16 的 Runtime 协议适配器、feature-t0 的任务接纳领域、feature-t2 的 Workflow 状态推进领域核心、feature-t6 的 Policy Gate 最小闭集与 feature-t3 的 Define Task / Review Definition 环。生产入口 `serve-stdio` 的 DomainPort 现在由 feature-t2 的正式 Domain Core 提供：给出可用的产品线仓时 `health` 为 `ready` 并投影接纳、Workflow 与 Definition 三组 capability 和 action；没有给出仓库或仓库不可用时仍然启动，但 `health` 为 `degraded` 并如实给出原因。standalone CLI 与受托 serve-stdio 是同一个 Domain Core 的两个调用面，共用同一把写者锁、同一份 bootstrap 与 binding、同一个控制代次和同一份正式状态。测试入口运行真实 stdio 协议进程，领域事实与 Host 是明确的合成输入。它不代表实施与验证环、Policy Gate、真实 Agent 执行、真实发布、安装包或完整 M-04 旅程已经交付。

## 环境与入口

开发验证环境为 CPython 3.12、macOS arm64。`requirements.lock` 固定所有直接和传递依赖及 wheel SHA-256；从仓根创建独立环境，不修改全局 Python，也不在 Runtime 启动时下载：

```sh
python3.12 -m venv apps/harness/.venv
apps/harness/.venv/bin/python -m pip install --require-hashes -r apps/harness/requirements.lock
apps/harness/.venv/bin/python apps/harness/hp.py serve-stdio --launch-config /absolute/path/launch.json --repository /absolute/path/product-line
```

`--repository` 是 Domain Core 绑定的唯一产品线仓；也可以改由 `launch.json` 的 `repository` 字段给出。两者都来自启动方，不从 wire 请求反推。两者都缺失或仓库不可用时 Runtime 仍启动，`runtime.health` 返回 `degraded` 并给出原因，不伪称领域已安装。

`hp.py` 的每个入口（serve-stdio、standalone CLI 各命令组、binding 与 bundle 模式）在分派前从本进程环境移除七个仓库定位类 Git 变量（GIT_DIR、GIT_WORK_TREE、GIT_INDEX_FILE、GIT_OBJECT_DIRECTORY、GIT_ALTERNATE_OBJECT_DIRECTORIES、GIT_COMMON_DIR、GIT_NAMESPACE），只把被移除的名称写到 stderr；领域与构建器的 git 调用另以同一清单剥离。因此在 Git 钩子等设置了这些变量的环境中运行时，读写的仍只是 `--repository` 或绑定文件指定的仓。GIT_SSH_COMMAND、GIT_ASKPASS 等传输与认证变量保留。

`launch.json` 是启动方从可信安装/进程记录提供的输入，不从 wire 请求反推。必需字段是 installationId、instanceId、incarnationId、connectionId、bundleDigest、dataFormat、launchAuthorization，另有 executionProfileRequirements 数组。launchAuthorization 的原值必须与 initialize 完全相同，且期限有效。此文件不是任意调用方自授资源权限的方式。Runtime 开发 bundle 不使用此文件：身份由 Initialize 给出、以包内自核的真实摘要核对，仓由实例目录的绑定文件给出，见「Runtime 开发 bundle（feature-t18）」一节。

从仓根运行产品测试和可审计的符合性报告：

```sh
HP_BUNDLE_INPUTS_DIR=<构建输入目录> HP_BUNDLE_OPENSSL=<OpenSSL 3 程序> apps/harness/.venv/bin/python -m unittest discover -s apps/harness/tests -p 'test_*.py'
HP_BUNDLE_INPUTS_DIR=<构建输入目录> HP_BUNDLE_OPENSSL=<OpenSSL 3 程序> apps/harness/.venv/bin/python apps/harness/tests/run_contract_conformance.py --output <短路径的新目录>
```

完整套件包含 feature-t18 的 `test_bundle`，它以被测代码构建 Runtime 开发 bundle，因此需要两个显式环境变量：`HP_BUNDLE_INPUTS_DIR` 指向构建输入目录（按 `bundle/inputs.lock.json` 的布局存放固定摘要的解释器资产与 `requirements.lock` 所列 wheel），`HP_BUNDLE_OPENSSL` 指向用于交叉验签的 OpenSSL 3 程序（系统 LibreSSL 不支持该用法）。两者没有缺省值：`test_bundle` 有五个测试类，缺少 `HP_BUNDLE_INPUTS_DIR` 时构建 bundle 的四个（`BuildCase`、`AdmissionCase`、`LaunchCase`、`MinimalPathCase`）在 setUpClass 以 `MissingInput: HP_BUNDLE_INPUTS_DIR is not set: ...` 报 ERROR，判定宿主版本的 `MinimumOsCase` 不需要构建输入；缺少 `HP_BUNDLE_OPENSSL` 时交叉验签用例以 `MissingInput: HP_BUNDLE_OPENSSL is not set: ...` 报 ERROR；`run_bundle_report.py` 缺任一变量即以该变量名退出。安装或启动 bundle 的用例要求本机 macOS 不低于 bundle manifest 的 `minimumOs`（`bundle/manifest.py` 的 `MINIMUM_OS`），与接收方准入的判定相同；低于时这些用例以 `host macOS <版本> is below the bundle minimumOs <版本>` 为原因 skip，其余用例照常运行。符合性报告的 `--output` 请取较短的目录：用例把合成 Agent 登记在该目录下，命令路径超过 feature-t4 登记的 256 字符上限时，相关用例会以 REGISTRATION_INVALID 报 ERROR。

output 必须不存在。每次运行保存测试结果、真实帧、合成 Git 状态与中断证据、环境、源码/依赖散列、逐方法覆盖及 AC 映射。失败原件不覆盖。测试报告的成功不自行产生 Human done、发布或双方接收决定。

独立 Host 可以只使用下面的显式测试入口，不必导入 dispatcher 或我们的 Host driver：

```sh
apps/harness/.venv/bin/python apps/harness/tests/make_fixture.py /absolute/path/new-test-fixture
apps/harness/.venv/bin/python apps/harness/tests/serve_synthetic.py serve-stdio --launch-config /absolute/path/new-test-fixture/launch.json --seed /absolute/path/new-test-fixture/seed.json --repository /absolute/path/new-test-fixture/domain
```

生成的 host-template.json 含 initialize、binding、scopeRef、action 和 evidence 示例。Grant 的 operation 使用完整 Runtime 方法名，capability 使用领域登记身份；每种访问都检查相应方法授权。测试 Git 仓必须有 `.synthetic-hp-domain` 标记，测试启动器不接受未标记仓。`--fault-config` 只存在于测试启动器，由测试 GitDomain 在指定 operation 的事务提交前/后发送 SIGKILL，生产命令没有这个参数。

## 代码与接入边界

| 路径 | 职责 |
| --- | --- |
| runtime/protocol.py | 冻结 schema/methods、严格帧解码、RFC 8785 摘要、本地预装 Registry |
| runtime/transport.py | 双向管道、请求关联、限额、控制/事件公平发送和反向调用超时 |
| runtime/dispatcher.py | 协商、scope 授权、分页和事件、操作幂等、资源读取、升级事务 |
| runtime/host.py | Host 反向方法的 schema、摘要、关联和错误校验，不实现物理执行 |
| domain/port.py | 领域单一事务接口；没有 Host、Runtime 或 JSON Schema 依赖 |
| domain/store.py | 持久适配与两入口协调面：`refs/harness/runtime`、`<git-common-dir>/harness/` 下的 `writer.lock`、`bootstrap.json` 与 `binding.json`（repo-layout §8.1 点名的成员）；CAS 提交、共享 domainRevision、控制代次栅栏、锁等待与外部漂移判定 |
| domain/core.py | feature-t2：生产 Domain Core（接纳 + Workflow）与 `apply_command`，两入口共用的唯一命令执行点；无法使用时给出 DegradedDomain 及原因 |
| domain/capability_schema.py | capability 文档的构造与 R2 核对（OD-425）：主 action 的 payload schema 为根，其余 action 为根 `definitions` 下以 actionId 命名、以 actionId 为 title 的自包含项 |
| domain/projection_stream.py | 投影重建的唯一入口（Assistant KB-296）：与上次提交的投影逐对象比较，未变对象保留 revision，新增或变化的对象取本次提交的 domainRevision，action 的 expectedRevision 绑定目标对象的当前 revision；每项变化在同一事务内以 object / action / pending 的 upsert 与 remove 事件追加到该 scope 的有序流 |
| domain/workflow/topology.py | feature-t2：从冻结拓扑正本读取稳定节点/边身份与节点语义类型；只读，不新增 Node、Edge 或 Gate |
| domain/workflow/states.py | feature-t2：五层正式状态与合法组合矩阵、标准 condition 路径、可重开判定 |
| domain/workflow/progression.py | feature-t2：Progression Commit 六步同一事务、trigger 事实与消费、attempt、任意时点终止、发布终态与终态槽位写入；feature-t3 增加用途无关的 `start_attempt`（CREATED→RUNNING） |
| domain/workflow/recovery.py | feature-t2：四类互斥恢复判定、判定到动作的唯一映射、单次消费与 Human 单次授权边界 |
| domain/workflow/reservations.py | feature-t2：领域侧预约；完成、超时或取消都不自动释放 |
| domain/workflow/projection.py · schema.py | feature-t2：Workflow 只读投影与两个 Runtime action 的 payload schema |
| domain/acceptance/ | feature-t0：来源核验与 Canonical Source Anchor（sources.py）、终态事实与并发计数（terminal.py）、原子接纳与幂等/去重/claim（accept.py）、结果闭集（results.py）、Runtime 投影与 action 绑定（projection.py、schema.py、runtime_binding.py） |
| domain/policy/ | feature-t6：Policy Gate 最小闭集。rules.py 判定项、评估对象、适用表与规则集身份；inputs.py 只读输入（活体 Registry、产品侧作者厂商映射、评审轮次、Git 对象；Implementer 登记读取器可注入）；items.py 逐判定项纯函数；evaluate.py 请求校验、汇总与 `policy-decision` 记录写入；authorize.py 执行端口生产授权回调；results.py 结论、原因码与退出码 |
| cli/main.py | feature-t0 的 `harness task resolve` / `task accept [--dry-run]` / `config set` 与 feature-t2 的 `harness workflow <command>`，调用与 Runtime action 相同的 `accept_task` 与 `apply_command`；feature-t4 的 `implement` / `verify` 两组子命令与 `config set implementer-ports` 由 cli/implement_verify.py 实现 |
| domain/definition/ | feature-t3：Define Task 与 Review Definition 环（候选与模板结构门 candidate.py、开关/端口/判词与失败分类 review.py、Definition 门 gate.py、裁定生成与两阶段写入 rulings.py、命令 commands.py、评审执行器 dispatch.py、Runtime 投影与 schema） |
| runtime/executions.py | feature-t3：用途无关的执行层（执行描述调度、结算、重启只查询）与生产执行端口工厂 `build_port`；feature-t4 在其上登记 coding-implementer 执行器，并在 `build_port` 中增加该用途的端口构造（产品侧登记、端口用途、每次重新发现程序身份） |
| cli/definition.py | feature-t3：`harness definition <submit|revise|dispatch|query|decide|formal-authorize|status>` |
| tests/definition_fixture.py · serve_definition.py · test_definition.py · test_definition_runtime.py | 仅测试：合成产品线仓、合成 Registry/评审方/授权回调、注入合成执行器的测试启动器与两入口测试 |
| tests/run_definition_report.py | feature-t3 逐 AC 离线验收报告生成器 |
| domain/implement_verify/ | feature-t4：实施派发核对（dispatch.py）、实施 attempt 与候选路由（implement.py）、物理执行事实结算（settlement.py）、Verify 适用检查与三种结果（checks.py、verify.py）、恢复判定产出（assessment.py）、产品侧 Implementer 登记（registration.py）、对 feature-t3 / feature-t6 的唯一接缝（seams.py）、执行器（executors.py）、Runtime capability 与 action 的投影和 payload schema（projection.py、schema.py） |
| execution/implementer_local.py · implementer_supervisor.py | feature-t4：独立模式实施端口与独立监督程序（`<git-common-dir>/harness/executions/<executionRequestId>/`） |
| domain/budget/ | feature-t5：三处 autonomous budget。配置键 `autonomous-budget` 的校验与带修订的只追加历史（configuration.py）、从 Progression Commit、Continue 决定事实与既有判定记录推导窗口、授予、消耗与完整性的纯函数（ledger.py，不导入 `domain/policy/`）、`budget-decide` 命令与预算节点上的通用命令收窄（commands.py）、结果闭集（results.py）、Runtime capability 与 action 的投影和 payload schema（projection.py、schema.py） |
| domain/validation/ | feature-t5：Validate Change 环。配置判定（config.py）、评审派发与 Owner formal 授权（dispatch.py）、候选变更文档与引用材料（materials.py）、impl 轮评审执行器（review.py）、判词核对、七类语义与结算（verdict.py）、finding 处置、带保留接受与 Continue 后续接（gate.py）、任务台账与 Publish 授权语境视图（records.py）、命令与通用命令收窄（commands.py）、结果闭集、投影与 schema |
| cli/validation.py | feature-t5：`harness budget <decide|status>`、`harness validate <configure|formal-authorize|dispatch|run|dispose|decide|resume|status>` 与 `config set autonomous-budget` |
| tests/product_line.py · acceptance_fixture.py · serve_acceptance.py · accept_with_fault.py | 仅测试使用：合成产品线仓、Runtime 接纳夹具、注入接纳领域的测试启动器、断点 SIGKILL 运行器 |
| tests/run_acceptance_report.py | feature-t0 逐 AC 离线验收报告生成器 |
| tests/workflow_fixture.py · serve_workflow.py | 仅测试使用：已接纳任务的 Workflow 夹具与注入生产 Domain Core 的测试启动器 |
| tests/run_workflow_report.py | feature-t2 逐 AC 离线验收报告生成器 |
| tests/policy_fixture.py · test_policy.py · run_policy_report.py | feature-t6：合成夹具（他任务事实按 design 同形合成并标注）、Policy Gate 测试与逐 AC 离线验收报告生成器 |
| tests/implement_verify_fixture.py · implement_verify_host.py · implement_verify_stdio.py | 仅测试使用：feature-t4 的合成产品线仓、合成 Agent 与合成 feature-t5 预算判定，合成嵌入 Host 及其对 serve-stdio 真实进程的 Contract 形态应答 |
| tests/run_implement_verify_report.py | feature-t4 逐 AC 离线验收报告生成器 |
| tests/validation_fixture.py · validation_stdio.py · guarded_walk.py · test_budget.py · test_validation.py | 仅测试使用：feature-t5 的合成产品线仓、明确标注的合成 impl 轮评审方与合成 Host，serve-stdio 真实进程的合成 Host 应答，他任务测试在收窄节点上的合成直接推进辅助 |
| tests/run_validation_report.py | feature-t5 逐 AC 离线验收报告生成器 |
| domain/publish/ | feature-t7：Publish 与受控恢复。发布目标配置 `publish-target`（configuration.py）、Publish 授权语境与摘要（context.py）、精确授权绑定核对与派生字段（binding.py）、Publish Authorization Gate 入口与通用决定收窄（gate.py）、push 许可与派发和执行开始（dispatch.py）、GitHub 平台适配器（platform.py）、推送与 Pull Request 创建或识别和同一 operation 查询（executor.py）、结果结算与恢复判定推导（settle.py）、查询与 Human 授权的补救（recovery.py）、任务台账 `publish`（records.py）、命令表与两个 Publish 节点上的通用命令收窄（commands.py）、结果码闭集（results.py）、Runtime capability 与 payload schema（projection.py、schema.py） |
| cli/publish.py | feature-t7：`harness publish <context|authorize|dispatch|run|query|reconcile|status>` 与 `config set publish-target`；绑定参数同样用于 `validate decide` |
| tests/publish_fixture.py · publish_stdio.py · test_publish.py | 仅测试使用：feature-t7 的合成产品线仓、本机 bare 远端（pre-receive 钩子可拒绝或拖延后拒绝）、明确标注 SYNTHETIC 的平台程序（`gh api` 接口，状态为 JSON 文件）、serve-stdio 真实进程的合成 Host |
| tests/run_publish_report.py | feature-t7 逐 AC 离线验收报告生成器 |
| tests/git_domain.py | 仅测试使用的 Git 持久 adapter，状态归合成仓 refs/harness/runtime |
| tests/host_driver.py | 独立预期的真实管道 Host 测试驱动；不导入 dispatcher |
| bundle/ | feature-t18：发布方构建工具（不是产品命令）。archive.py 确定性 ustar 读写（也随包供 Runtime 自核）、layout.py 组成规则与只读精确提交的源码树、manifest.py 描述件、release.py 发布记录与经 OpenSSL 子进程的 Ed25519 分离签名、probe.py 在暂存解释器内的构建探针、build.py 构建入口、inputs.lock.json 第三方构建输入身份 |
| runtime/launch.py | feature-t18：`serve-stdio --bundle` 启动模式（契约摘要参数、包自核、Initialize 身份采纳与摘要核对、实例绑定文件与 scope 句柄核对、仓库定位类 Git 变量的剥离，hp.py 入口同样调用）与 `hp binding write / show` |
| tests/bundle_fixture.py · bundle_host.py · ed25519_synthetic.py · test_bundle.py · run_bundle_report.py | 仅测试使用：以被测代码与 SYNTHETIC 内存密钥构建的 bundle、篡改变体、复现接收方准入与启动方式的合成 Host、纯 Python Ed25519、bundle 内最小路径与逐 AC 离线验收报告生成器 |

DomainPort 的 transaction 回调只构造待提交领域状态，禁止外部副作用。generation、完整幂等索引、Operation、投影事件与升级释放修订必须原子保存；普通 `intent=domain` 写者服从持久屏障，协议控制事务仍不能在屏障后新增保护引用。只有可查询的已接受记录才可由后继执行层驱动副作用。`accept_action` 由领域方实现，它是未来 Workflow 合法集合与自身前提检查的边界，不是 Runtime 新建的任务状态机。正式 Domain Core 还须实现共享 writer.lock、绑定、CAS 提交、漂移判断、保护引用与自身恢复规则，不能直接把测试 GitDomain 改作生产 adapter。

领域状态视图包含 revision/generation、bindings/scopes、operations/keys/indexComplete、resources、protectedReferences、upgrades/barrier/dataFormat 和 quiesced/shutdown；scope 提供 objects/actions/pendingItems 与 streamId/epoch/seq/logFloor/events。这些是适配器所需的内部接口数据，领域决定仍由正式存储层保存。`revision` 是共享 domainRevision；只读重传不得产生新 revision。对象的 revision 是对象级的：只在该对象自身内容变化时推进为当次提交的 domainRevision，其他对象的提交不使它过期；快照水位之后按事件重放得到的投影与同一时点的新快照逐对象相等（`tests/test_projection_events.py`）。快照缓存是可重建连接数据，不是领域正本；租约60秒，最多8个未过期快照且合计32MiB，超限明确拒绝。全部历史事件由本测试 adapter 保留，生产日志压缩必须遵守快照/订阅保护水位。

capability schema 由安装方显式提供本地 Registry，登记摘要采用该 schema 的 RFC 8785 bytes SHA-256；未知引用、网络与任意文件检索均拒绝。capability 的 schemaDigest 与 action 的 payloadSchemaDigest 均须实际指向安装的内容。没有从请求获取 schema 的入口。按 Owner 裁定 OD-425（Assistant KB-301），每个 capability 声明的文档是其主 action 的 payload schema，同一 capability 其余 action 的 payload schema 是该文档根 `definitions` 下以 actionId 命名的一项，自包含（无 `$ref`、无嵌套 `$id` 与 `$schema`），并带 `"title": "<actionId>"`，各项摘要互不相同且不同于文档摘要（`domain/capability_schema.py`）；action 的 payloadSchemaDigest 等于文档摘要或恰好一项的 RFC 8785 SHA-256，Runtime 只在该 action 已协商 capability 的文档内解析（`runtime/protocol.py` 的 `Schemas.resolve`），解析不到即以 UNSUPPORTED_CAPABILITY 拒绝，不按已安装但未在该 capability 内的 schema 执行。文档因此改变的 capability 升版本：harness.workflow、harness.definition、harness.implement-verify、harness.validate-change、harness.publish 为 2，harness.task-acceptance 与 harness.autonomous-budget 仍为 1。

Host resource.read 客户端逐块检查真实 Base64、请求长度与证据剩余长度、offset 和 EOF；单块覆盖整个证据时直接核 SHA-256。多块消费者必须在使用内容前按 offset 拼接、核总字节数与完整 SHA-256，逐块声明的 digest 相同不能代替该检查。当前反向客户端没有宣称多块拼接已经由后继消费者完成。

固定 Contract 0.1.0 保持上游 draft.5 原字节；contract/schema.json 与 methods.json 是原件复制，不改写版本标记。源输入身份及旧 draft.4 transcript 归 `records/diagnostics/feature-t16/2026-09-21/inputs.json`。原 Assistant 静态校验已有270项通过，属于输入准备证据；新 Runtime 报告单列，旧32份 transcript 不迁移或改写。旧 fixtures 的 INVALID_SOURCE 与 required capability 自身 schemaDigest 残留由新用例补证时，只声称新实现用例结果。

## 任务接纳（feature-t0）

接纳只读核验产品线仓内的四件来源：`sdd/proposal.md`、`sdd/spec.md`、`sdd/milestones.md` 与名单中唯一命中的任务行。每个文档按页首 `权威状态: subject` 取 subject，再核 `records/governance/<subject>/freeze-records.jsonl` 末行（`exit` 为 freeze 或 freeze-with-reservation，且 objects 内该路径的 bytes/sha256 与基准 ref 中的字节一致）；任务行按 milestones 模板文法解析，WITHDRAWN 行无资格。结果为 RESOLVED / UNRESOLVED / INDETERMINATE 三态，逐件 component 给出原因。仓库引用先经 `gitrepo.probe` 分类：路径不存在、根下无 `.git`、gitdir 指针指向不存在目录，或 `.git` 可访问但 git 判定非有效仓库，为确定性缺失（UNRESOLVED）；路径或 `.git`（含 gitdir 指向的目录）存在但 EACCES / 不可访问，以及 git 生成失败或超时，为暂不可判（INDETERMINATE）。git 以 `GIT_CEILING_DIRECTORIES` 限定在给定路径，不向上发现外层仓库；RESOLVED 绑定可复现的 Canonical Source Anchor（根提交仓身份、来源修订、逐件 blob/bytes/sha256/subject/冻结修订、milestone 与任务行原文、依赖列表、Workflow 拓扑文件身份）。

```sh
apps/harness/.venv/bin/python apps/harness/hp.py task resolve --repository <产品线仓> --type feature --task-id feature-t0 --base-ref origin/main
apps/harness/.venv/bin/python apps/harness/hp.py task accept --repository <产品线仓> --type feature --task-id feature-t0 --base-ref origin/main \
  --request-id <稳定请求身份> --authority-ref <Owner 授权定位> --worktree-root <仓外绝对目录> [--dry-run]
apps/harness/.venv/bin/python apps/harness/hp.py config set concurrency-limit 4 --repository <产品线仓> --authority-ref decisions/D-09-parallel-task-start-form.md
```

接纳次序：Operation 记录 → 只读来源核验 → claim 提交（依赖终态、并发容量、去重 claim、意向分支/worktree 与 anchor）→ `git branch harness/<task-id> <来源修订>` → `git worktree add <root>/harness/<task-id>` → Acceptance Commit Point（Task、绑定、Workflow Instance 初始记录：拓扑身份、`Human · Define Task`、生效评审开关）。Task 只在最后一次提交后可见。同 requestId 同意图重试返回同一结果或续完同一 Operation；同 requestId 异意图为 REQUEST_CONFLICT；不同请求命中同一上游任务得到 DUPLICATE_ACCEPTED_TASK / DUPLICATE_ACCEPTANCE_IN_PROGRESS；claim 不自动释放；断点后重试先核既有分支指向来源修订、worktree 注册与意向一致，否则 PARTIAL_EFFECT_UNRESOLVED 停报，不删除任何对象。并发上限来自领域状态 `configuration.concurrencyLimit`（缺省 1；未终态 Task 与 claimed Operation 共同计数，终态 = 领域 terminal 槽位或基准 ref 树内 `tasks/<id>/rulings/` 的 `Type: done|close` 裁定件）。结果闭集与退出码见 `domain/acceptance/results.py` 与 `cli/main.py`。

Runtime 侧登记 capability `harness.task-acceptance` 与 action `task.accept`（payload schema `urn:hp:harness:task-acceptance:v1`，`requiresHumanDecision` 为 true）：dispatcher 先核 Grant、可信 DecisionRecord 与 payload schema，再持久接纳 Operation；同进程执行层随后调用同一 `accept_task`，把结果写回 Operation（succeeded 时 resultRef 指向可经 `runtime.resource.read` 读取的结果 JSON；确定性拒绝为 failed，resultCode 为原因码的连字符形态；INDETERMINATE / PARTIAL_EFFECT_UNRESOLVED 为 unknown）。生产 `serve-stdio` 仍注入 `UnavailableDomain`，接线归 feature-t2；测试通过 `tests/serve_acceptance.py` 注入。

```sh
apps/harness/.venv/bin/python apps/harness/tests/run_acceptance_report.py --output tasks/feature-t0/attempts/my-new-run
```

报告逐 AC 给出 PASS / FAIL / NOT_RUN，固定源码、输入与环境身份；生产接线、J-03、J-07 与真实任务保持 NOT_RUN。测试只使用带 `.synthetic-hp-domain` 标记的合成产品线仓；hotfix 来源解析归 feature-t1（请求以 SOURCE_LANE_UNAVAILABLE 拒绝）。

## Workflow 状态推进（feature-t2）

正式状态分五层，互不混用：Workflow Lifecycle（ACTIVE / COMPLETED / CLOSED）、Current Position（绑定的不可变拓扑修订 + 稳定节点身份 + 本次进入的 occurrence）、Execution Condition（ENTERED / EXECUTING / AWAITING_HUMAN_ACTION / RESULT_RECORDED / RECOVERY_REQUIRED）、Attempt（CREATED / RUNNING / COMPLETED / EXECUTION_FAILED / INDETERMINATE）与 Progression Commit。组合必须落在按节点语义类型分列的合法矩阵内；Publish 在 ACTIVE 时只允许 ENTERED / EXECUTING / RECOVERY_REQUIRED，终态只有「COMPLETED + Publish + RESULT_RECORDED」与「CLOSED + RESULT_RECORDED」两种。业务 FAIL 是可消费的正式结果，沿既有 FAIL 边继续；只有执行失败、结果完整性破坏或完成状态不确定才进入 RECOVERY_REQUIRED。

拓扑身份取自 `mechanisms/delivery-method/MVP_Workflow_v5.drawio` 的 `topologyNodeId` / `topologyEdgeId` / `semanticType`（当前为 35 个节点与 45 条边），只读、零改动；draw.io 的 mxCell id 只用于解析边端点，不是产品身份。每次状态改变形成一条不可变 Progression Commit，六步在同一事务内完成：核期望 Runtime Version、核 trigger 属当前位置与用途且未消费、核所选边从当前节点出发且目标落在合法矩阵、写入记录、绑定 trigger 消费、更新快照与版本。

Human Gate 的合法决策集由拓扑位置推导：Definition 授权门的 Authorize & Freeze，三处 escalation 门的 Continue 与 Close Task（Definition 与 Validation 两处另有 Accept With reservation），以及最终 Publish authorization。任意时点终止对任一未终态任务成立且方向单向：经 escalation 门时选该门的 Close Task 边并落在登记的 Close 节点，其余位置作为任务生命周期层的权力动作就地终止，两者都在同一次提交内形成 CLOSED + RESULT_RECORDED，不存在中间的未终结关闭态。终止后 in-flight attempt 记为被终止，不伪造完成或失败；已发布任务不可终止；终止理由类别机械区分「Human 主动终止」与「阻塞升级」。

恢复只在当前 occurrence 内进行，判定产生四类互斥结果，每类映射唯一动作：已确认结果在非发布节点记为 RESULT_RECORDED、在发布节点走窄化的 EXECUTING 终态兼容路径；可安全重开回到 ENTERED；需要就地对账保持恢复条件并要求重新判定；不可判定不产生任何状态改变，且任何路径都不能把它改写为其他三类。判定单次消费，位置、occurrence 或 Runtime Version 变化即失效。重开节点、会改外部状态的对账与需要扩权的取证各需一次性的 Human Recovery Action Authorization，绑定实例、occurrence、期望版本、判定引用、精确动作与允许的影响范围。预约在完成、超时或取消时都不自动释放，只有指名同一执行事实的结算才释放。

```sh
apps/harness/.venv/bin/python apps/harness/hp.py workflow status --repository <产品线仓> [--task-id <id>]
apps/harness/.venv/bin/python apps/harness/hp.py workflow condition --repository <产品线仓> --task-id <id> \
  --command-id <唯一命令身份> --condition RESULT_RECORDED --authority-ref <授权定位>
apps/harness/.venv/bin/python apps/harness/hp.py workflow advance --repository <产品线仓> --task-id <id> \
  --command-id <唯一命令身份> --edge E-D01 --authority-ref <授权定位> [--trigger <factId>]
apps/harness/.venv/bin/python apps/harness/hp.py workflow decide --repository <产品线仓> --task-id <id> \
  --command-id <唯一命令身份> --decision "Authorize & Freeze" --authority-ref <授权定位>
apps/harness/.venv/bin/python apps/harness/hp.py workflow close --repository <产品线仓> --task-id <id> \
  --command-id <唯一命令身份> --reason-category human-initiated --authority-ref <授权定位>
```

其余子命令为 `fact`、`publish-finalize`、`attempt-open`、`attempt-settle`、`reserve`、`reservation-settle`、`recover-assess`、`recover`。每个状态改变型命令先取控制代次再写，因此仍持旧代次的另一入口会被 STALE_CONTROL_GENERATION 拒绝，且该拒绝与 VERSION_CONFLICT、EXTERNAL_DRIFT 各自独立。`--lock-wait <秒>` 让调用方在有界等待后以 LOCK_UNAVAILABLE 报告而不是一直阻塞。结果与拒绝闭集见 `domain/workflow/results.py`；退出码 0 已提交、1 已查明拒绝、2 未查成。

Runtime 侧登记 capability `harness.workflow` 与两个 action `workflow.decide`、`workflow.close`（均 `requiresHumanDecision`）。合法动作集合由当前状态推导：没有任务停在 Human Gate 时 `workflow.decide` 投影为 disabled，dispatcher 在提交前重取该 action，禁用或变化即拒绝，因此界面不能创造权限。Workflow 命令没有外部副作用，所以在接受 Operation 的同一事务内执行，Operation 索引使重复调用幂等，结果经 `runtime.resource.read` 读回。

```sh
apps/harness/.venv/bin/python apps/harness/tests/run_workflow_report.py --output tasks/feature-t2/attempts/my-new-run
```

报告逐条给出 AC-01 至 AC-09 的 PASS / FAIL / NOT_RUN，固定源码、依赖与环境身份，并写明后继任务的消费约束；J-03、J-04、J-05、J-07 与真实模型保持 NOT_RUN。写者锁是合作入口协议，不阻止同账户外部程序直改仓库：这种改动由漂移判定固定事实并停报，不自动回滚也不换请求身份重试。

## Policy Gate（feature-t6）

Policy Gate 是 Policy Decision 唯一的产生点。它对固定闭集的判定项作 fail-closed 评估：作者实际厂商集合、Reviewer 资格、输入证据、profile 用途与执行端、Human authority、精确 push 许可、预算；评估对象闭集为 `review-release`、`implement-release`、`push-permit`，每个对象的适用判定项由 `domain/policy/rules.py` 的固定表给出。任一适用项 FAIL 为 DENY，无 FAIL 而有 NOT_CHECKED 为 NOT_DETERMINABLE，只有全部 PASS 才是 ALLOW；输入缺失、不可读、身份不符或来源不可信都不产生 ALLOW。每次评估在同一写者锁与控制代次下写入一条不可变 `policy-decision` 事实（记录身份是整条决定内容的摘要），不移动当前位置、执行条件、生命周期或 Runtime Version。

`policy-decision` 事实只能由 Policy Gate 写入：通用 `workflow fact` 写入该类事实被拒绝，推进消费 trigger 时只接受 Policy Gate 产生且结论为 ALLOW 的记录。执行端口、评审通道与各环的既有核对保留为纵深防御，它们可以更严，但不产生 Policy Decision，也不能在 Policy 未允许时放行。

作者厂商映射由产品侧 Domain 配置承载（Assistant OD-399），键为执行记录中的 agent 身份与模型身份、值为评审通道 `VENDORS` 闭集内的厂商，精确匹配，缺失即 DENY；评审通道 Registry 的 `model_mappings` 不作作者厂商来源，Reviewer 资格与评审方厂商仍读 Registry 的 Reviewer 端口条目。profile 判定比较摘要、用途与操作，不比较 programIdentity（版本无关）。执行边界按 profile 声明原样记入决定：当前 macOS 账户内的受信任本地执行，不声称强隔离或机械阻断任意 Agent 操作。Coding 执行没有美元费用上限，预算字段闭集为 maxToolCalls、maxRunSeconds、maxOutputBytes、cleanupSeconds。

```sh
apps/harness/.venv/bin/python apps/harness/hp.py config set author-vendor Anthropic --agent agent:claude-code \
  --model 'claude-opus-5[1m]' --repository <产品线仓> --authority-ref <授权定位>
apps/harness/.venv/bin/python apps/harness/hp.py policy evaluate --repository <产品线仓> --task-id <id> \
  --request @<hp-policy-request/v1 JSON 文件> --authority-ref <授权定位>
apps/harness/.venv/bin/python apps/harness/hp.py policy show --repository <产品线仓> --task-id <id> [--fact-id <id>]
```

`policy evaluate` 的退出码即结论：0 ALLOW、1 DENY、2 NOT_DETERMINABLE；请求格式错误输出 `result = INPUT_INVALID`、不写记录、退出码 2，与 NOT_DETERMINABLE 按 `result` 字段区分。受托入口不新增 Runtime action：执行端口在 preflight、放行、查询、取消与恢复时调用 `domain/policy/authorize.py` 的 `execution_authorizer(domain, task_id, subject, entry, generation, *, context)` 返回的回调，回调经同一 `apply_command("policy-evaluate")` 评估，只在 Policy Gate 产生的 ALLOW 下返回 `ExecutionAuthorization`，其 `authorization_ref` 即该记录身份，端口据此持久计数调用次数；同一 attempt 的补发调用得到同一记录身份，计数达上限的新调用以一条独立的 DENY 记录拒绝。实施放行读取的 Implementer 登记由 feature-t4 的产品侧登记提供，未注入读取器时该放行为 NOT_DETERMINABLE。

```sh
apps/harness/.venv/bin/python apps/harness/tests/run_policy_report.py --output tasks/feature-t6/attempts/my-new-run
```

报告逐条给出 AC-01 至 AC-10 的 PASS / FAIL / NOT_RUN 与后继任务的消费调用点；J-04、J-05 与真实模型保持 NOT_RUN。

## Define Task 与 Review Definition（feature-t3）

Human 以任务分支上一个提交提交 Candidate Task Definition 并声明作者身份证据；领域从该提交读取字节（不读工作区），用产品线仓内与评审通道 Definition 核对同一个 `mechanisms/artifact-templates/artifact_lint.py` 做模板结构门，再核身份链与已接纳锚的 milestones 冻结修订。通过后沿 E-D01、E-D02 到 `Review Definition Enabled?`，按接纳时记录的开关走 E-D03 或 E-D04。开关关闭时定稿写 review-skip 与 finalization 两件裁定；开启时经 `definition dispatch` 派发评审，结果只以有效 task 轮五维判词进入，Host 取消、端口故障、授权回调拒绝与结果不确定都进入 RECOVERY_REQUIRED 而不是 FAIL。评审通道在分配 attempt 之前拒绝（不可路由的请求，或分配前的预检拒绝）且端口没有预约时，结果记为 `preflight_failed`，通道失败码与原文进入轮记录与 attempt 证据，预约以 `refused-before-release` 执行事实结算，Operation 随该轮结算为 failed；其余读不到发布结果的情形仍为结果不确定，通道报告与诊断随结果保存（Validate Change 同此）。含 human finding 的判词要先经 `Dispose findings` 写出 finding-disposition 裁定才推进。Definition 授权门的 Authorize & Freeze 与 Definition escalation 门的 Accept With reservation 只经 `definition decide`（通用 `workflow decide` / `workflow.decide` 对这两个决定以 `definitionEntryRequired` 拒绝，投影同步不列出）；裁定件先登记字节，再在任务 worktree 提交，最后推进，重试不重复写、不覆盖。embedded 端口为 CONFIGURED 时，`definition formal-authorize` 记录 Owner formal 授权事实供 feature-t6 回调读取。

```sh
apps/harness/.venv/bin/python apps/harness/hp.py definition submit --repository <产品线仓> --task-id <id> --command-id <身份> \
  --authority-ref <授权定位> --commit <任务分支提交> --author '<{"tool":…,"model":…,"vendor":…,"humanOnly":false,"evidenceRefs":[{"commit":…,"path":…}]}>'
apps/harness/.venv/bin/python apps/harness/hp.py definition dispatch --repository <产品线仓> --task-id <id> --command-id <身份> --authority-ref <授权定位>
apps/harness/.venv/bin/python apps/harness/hp.py definition decide --repository <产品线仓> --task-id <id> --command-id <身份> \
  --authority-ref <授权定位> --decision "Authorize & Freeze" --decision-text "<Human 原话>"
apps/harness/.venv/bin/python apps/harness/tests/run_definition_report.py --output tasks/feature-t3/attempts/my-new-run
```

执行层（`runtime/executions.py`）：需要事务外效果的领域命令只登记执行描述；serve-stdio 在接受 Operation 后把描述作为事件循环上的任务调度，执行期间照常应答查询、取消与快照，完成后在新的领域事务内结算 attempt、预约与 Operation；进程重启后对仍在运行的描述只查询同一请求，不再执行。它不扩展接纳的同步 `drain()`：评审需要 ProductReview 的工作线程把 Host 调用投回同一事件循环，同步等待会使事件循环自锁。生产端口工厂 `build_port` 对 review 用途从活体 Registry 取登记，其他用途由调用方以关键字传入登记；授权回调取 feature-t6 `domain/policy/authorize.py` 的 `execution_authorizer(domain, task_id, subject, entry, generation)`，未安装时拒绝放行；embedded 的 Host 连接事实只取可信启动配置的 `executionBindings`，缺失即拒绝。programIdentity 由端口每次执行重新发现并记入记录，不作登记前置。真实回调路径已在 AC-03/AC-09 的用例中运行（feature-t6 已合入）；Policy Gate 与评审通道统一读取所绑定产品线仓内的 `mechanisms/review-channel/review_channel_registry.json`。当前限制：archive-v1 的判词回读未实现（记为结果不确定）；真实评审与 J-04 真实资格未运行。

## Implement 与 Verify 环（feature-t4）

实施用途执行端口登记在产品线仓的领域配置中，不写评审通道 Registry（Assistant OD-399）。登记按 (portId, purpose) 唯一，profile 不含程序身份；程序身份每次执行重新发现并随执行记录，版本变化不单独导致拒绝：

```sh
apps/harness/.venv/bin/python apps/harness/hp.py config set implementer-ports '<JSON 条目列表>' --repository <产品线仓> --authority-ref <授权定位>
apps/harness/.venv/bin/python apps/harness/hp.py verify checks-set --repository <产品线仓> --checks '<JSON 检查声明列表>' --authority-ref <授权定位>
```

Definition 定稿后，派发、独立模式执行、Verify 与恢复经以下命令进行；输出为 JSON，退出码 0 已完成、1 已查明拒绝、2 未查成或不可判定：

```sh
apps/harness/.venv/bin/python apps/harness/hp.py implement dispatch --repository <仓> --task-id <任务> --command-id <id> --authority-ref <定位> \
  --port-id <端口> --worktree <任务 worktree> --finalization-ref RU-NN --budget '{"maxToolCalls":…,"maxRunSeconds":…,"maxOutputBytes":…,"cleanupSeconds":…}'
apps/harness/.venv/bin/python apps/harness/hp.py implement run --repository <仓> --task-id <任务> --execution-id <executionRequestId>
apps/harness/.venv/bin/python apps/harness/hp.py verify run --repository <仓> --task-id <任务> --command-id <id> --authority-ref <定位>
apps/harness/.venv/bin/python apps/harness/hp.py implement status|remediate|assess|route …
```

执行授权只由 feature-t6 的 `execution_authorizer` 以评估对象 `implement-release` 产生，经 feature-t3 的生产端口工厂 `build_port` 注入；本任务经 `HarnessDomain.policy_sources` 注入产品侧登记读取器，作者厂商映射读取 `config set author-vendor` 写入的同一配置。派发登记执行描述：独立模式的执行由 `implement run` 在 feature-t3 的执行层上运行，嵌入模式的执行由 serve-stdio 的执行层在启动或接受操作后调度。serve-stdio 另投影 capability `harness.implement-verify` 与 `implement.dispatch`、`verify.run` 两个 Runtime action（合法集合由 Workflow 状态推导，需 Host 的 Human 决定），与 CLI 执行同一领域命令；嵌入端口的 Agent launcher 与连接事实取自受信任启动配置 `executionBindings`，程序身份每次执行重新发现。停止未确认（J-06 r2 §3.1）、unknown 与失败都进入恢复条件并保持预约，Verification Result 一经记录不可改写。逐 AC 离线验收报告：

```sh
apps/harness/.venv/bin/python apps/harness/tests/run_implement_verify_report.py --output records/diagnostics/feature-t4/<日期>/<本轮目录>
```

报告列出唯一的合成替身（feature-t5 预算判定）；真实 Assistant Host、J-04、J-05、J-06 真实 Host 联调与真实模型保持 NOT_RUN。

## Validate Change 环与 autonomous budget（feature-t5）

三处 autonomous budget（Definition Review 重审、Verify remediation、Validate Change remediation）各自是有限的次数额度，由 Policy Gate 判定。产品线须先显式配置额度，不设缺省值；额度为 0 表示该环每次业务 FAIL 都直接升级 Human：

```sh
apps/harness/.venv/bin/python apps/harness/hp.py config set autonomous-budget '{"definitionReview":1,"verification":2,"validationReview":1}' \
  --repository <产品线仓> --authority-ref <授权定位>
apps/harness/.venv/bin/python apps/harness/hp.py budget decide --repository <仓> --task-id <任务> --command-id <id> --authority-ref <定位>
apps/harness/.venv/bin/python apps/harness/hp.py budget status --repository <仓> --task-id <任务>
```

`budget decide` 在任务停于预算节点（`N-DEF-BUDGET-DECISION`、`N-VERIFY-BUDGET-DECISION`、`N-VALIDATE-BUDGET-DECISION`）时，在一个事务内以评估对象 `definition-review-budget`、`verification-budget` 或 `validation-review-budget` 调用 Policy Gate 并按结论推进。余量与耗尽都是结论 ALLOW 的 `policy-decision` 记录，以 `payload.outcome`（`Budget Remains` / `Budget Exhausted`）区分（Assistant KB-264）；Verification 一处的记录由 feature-t4 的 `commands.remediate` 消费并沿 E-I08 / E-I10 推进，另两处沿各自的余量边或耗尽边推进，耗尽后 escalation 门进入等待 Human。DENY（到达不是由业务 FAIL 引起，或窗口内有未经判定的余量推进）与 NOT_DETERMINABLE（缺配置）的记录保留但不推进，退出码分别为 1 与 2。窗口起点为该环最近一次 Continue，没有 Continue 时为首次 FAIL 到达；窗口额度取窗口起点生效的配置，窗口起点时尚无配置则取其后首次写入的配置，窗口进行中改配置不改变该窗口额度。三处计数互不影响，执行失败与不确定不消耗额度。预算规则表独立成表（`BUDGET_RULE_SET_DIGEST`），既有三类评估对象的 `RULE_SET_DIGEST` 不变。

Validate Change 环在 Verify 通过后进入 `N-VALIDATE-CONFIG`。开关由接纳时的 `reviewConfiguration.changeValidation` 决定，本期缺省关（Assistant OD-388），关闭时 `validate configure` 记开关事实并沿 E-V02 到 Publish Authorization Gate，不产生 Reviewer Attempt。开启时：

```sh
apps/harness/.venv/bin/python apps/harness/hp.py validate configure --repository <仓> --task-id <任务> --command-id <id> --authority-ref <定位>
apps/harness/.venv/bin/python apps/harness/hp.py validate formal-authorize --repository <仓> --task-id <任务> --command-id <id> \
  --authority-ref <Owner 授权定位> --max-calls 1 [--port-id <端口>]
apps/harness/.venv/bin/python apps/harness/hp.py validate dispatch --repository <仓> --task-id <任务> --command-id <id> --authority-ref <定位> \
  [--port-id <端口>] [--round-extensions '<Human 加轮记录 JSON>']
apps/harness/.venv/bin/python apps/harness/hp.py validate run --repository <仓> --task-id <任务>
apps/harness/.venv/bin/python apps/harness/hp.py validate dispose --repository <仓> --task-id <任务> --command-id <id> --authority-ref <定位> \
  --decision-text "<Human 原话>" --findings '{"<finding id>":"<处置>"}'
apps/harness/.venv/bin/python apps/harness/hp.py validate decide --repository <仓> --task-id <任务> --command-id <id> --authority-ref <定位> \
  --decision-text "<Human 原话>" --reservation "<保留意见>" --candidate-commit <任务分支当前提交> --source-branch <任务分支> \
  --remote <远端名> --target-branch <目标分支> --title "<PR 标题>" --body-file <PR 正文文件> --context-digest <publish context 给出的摘要>
apps/harness/.venv/bin/python apps/harness/hp.py validate resume|status …
```

派发以确定性生成的候选变更文档（派发基准到候选提交的全部改动与 Verify 结论摘要）作为评审通道 impl 轮唯一候选，引用材料为已定稿 Definition、已接纳锚修订上的 proposal / spec / milestones 与候选提交上在场的任务 design；材料从 Git 对象物化到任务 ignored `attempts/validation/<round>/`，执行前逐件核字节。评审执行在 feature-t3 的执行层上以 `build_port` 构造 review 用途端口，授权回调为 feature-t6 的 `execution_authorizer`（评估对象 `review-release`，被审对象 kind `candidate-change`）；嵌入端口为 CONFIGURED 时须先记 Owner formal 授权事实。有效 impl 轮判词（schema、stage、五题题号集合与候选身份全部相符）以 EvidenceRef 记为 `reviewer-verdict` 事实并映射 FR-24 七类语义：PASS 沿 E-V04 到 Publish Authorization Gate，FAIL 沿 E-V05 到 Validation 预算节点；含 `human` finding 的判词先经 `validate dispose` 写出 finding-disposition 裁定。Host 取消、端口故障、提供方不可达、认证失败、超时、输出无效、preflight 拒绝与中断记为执行失败、节点进入恢复条件；结果未知与 J-06 停止未确认记为不确定、保持预约、只查询同一请求；两者都不走 FAIL 边、不消耗额度。impl 轮号只随已交付判词前进。

Validation escalation 门的合法决定为 Continue、Close Task 与 Accept With reservation。Continue 经通用决定到 `N-VALIDATE-CONTINUE`，随后 `implement dispatch` 取 E-V13 与 E-V08 回到实施（Runtime 入口可先以 `validate.resume` 取 E-V13），remediation 输入携带上一轮 Validation 判词与 Findings。Accept With reservation 只经 `validate decide`（通用 `workflow decide` / `workflow.decide` 以 `DECISION_REQUIRES_VALIDATION_ENTRY` 拒绝，投影不列出），同一事务内记带 decision context 的决定事实并沿 E-V12、E-V14 到 `N-PUBLISH`。三处预算节点与全部 Validate Change 节点上的通用 `fact`、`advance`、`condition`、attempt 与预约命令对任何任务都以 `GENERIC_COMMAND_NARROWED` 拒绝，任意时点终止与 Human 授权的恢复保留。`domain/validation/records.publish_context(state, task_id)` 为 feature-t7 提供 Publish 授权语境视图；经 E-V12 到达 Publish 的决定即该路径的 Publish 授权，同一决定事实携带 `publishBinding` 与 Publish 授权语境摘要，push 许可按该绑定评估（核对规则见「Publish 与受控恢复（feature-t7）」一节）。

serve-stdio 另投影 capability `harness.autonomous-budget`（action `budget.decide`）与 `harness.validate-change`（action `validate.configure`、`validate.dispatch`、`validate.formal-authorize`、`validate.dispose`、`validate.decide`、`validate.resume`），与 CLI 执行同一领域命令。逐 AC 离线验收报告：

```sh
apps/harness/.venv/bin/python apps/harness/tests/run_validation_report.py --output records/diagnostics/feature-t5/<日期>/<本轮目录>
```

报告逐条给出 AC-01 至 AC-11 的 PASS / FAIL / NOT_RUN、每个测试的合成产品线持久状态前后与推进边序列，ERROR 与 FAIL 分列；真实模型、真实评审方的 impl 轮跨模型提供方评审、J-03、J-04 真实资格、J-05、J-06 真实 Host 联调与 J-07 保持 NOT_RUN。

## Publish 与受控恢复（feature-t7）

Publish 只在 Human 对精确候选与目标授权之后执行，止于远端任务分支与 GitHub Pull Request 的创建或识别（C-07）；产品没有合并、关闭、编辑 Pull Request 或删除分支的动作。产品线须先显式配置发布目标，不设缺省值；平台本期只有 `github`（`gitlab` 配置被拒绝，Assistant KB-272）：

```sh
apps/harness/.venv/bin/python apps/harness/hp.py config set publish-target \
  '{"provider":"github","host":"github.com","repository":"<owner/name>","repositoryId":"<数字 id>","remote":"origin",
    "remoteAddress":"<该远端推送地址>","targetBranch":"main","cli":"<平台命令行程序绝对路径>"}' \
  --repository <产品线仓> --authority-ref <授权定位>
apps/harness/.venv/bin/python apps/harness/hp.py publish context --repository <仓> --task-id <任务>
apps/harness/.venv/bin/python apps/harness/hp.py publish authorize --repository <仓> --task-id <任务> --command-id <id> \
  --authority-ref <Human 决定定位> --decision-text "<Human 原话>" --candidate-commit <任务分支当前提交> \
  --source-branch <任务分支> --remote <远端名> --target-branch <目标分支> --title "<PR 标题>" --body-file <PR 正文文件> \
  --context-digest <publish context 给出的摘要>
apps/harness/.venv/bin/python apps/harness/hp.py publish dispatch --repository <仓> --task-id <任务> --command-id <id> --authority-ref <定位>
apps/harness/.venv/bin/python apps/harness/hp.py publish run --repository <仓> --task-id <任务>
apps/harness/.venv/bin/python apps/harness/hp.py publish query|reconcile|status …
```

`publish context` 输出 Publish 授权语境（已定稿 Definition 与各轮 Definition 评审、Definition 侧 reservation、路由候选与 Verification Result、Validate Change 开关事实与各轮判词、reservation 与预算判定、全部 Policy Decision、两个 Review 开关与来源、发布目标、任务分支当前提交）、它的摘要与建议绑定。`publish authorize` 只在 Publish Authorization Gate 等待 Human 时可用：领域核对候选等于任务分支当前提交、源分支是接纳时绑定的任务分支、远端与目标分支和推送地址等于配置、Verify 确认的候选是其祖先且二者之间只有本任务领域写入的裁定提交（Assistant KB-265）、标题单行、正文限长、摘要未过期，任一不符以带字段路径的原因拒绝；通过后决定事实携带完整 `publishBinding` 并沿 E-V06 到 Publish 节点。通用 `workflow decide` 提交 Publish authorization 以 `DECISION_REQUIRES_PUBLISH_ENTRY` 拒绝。E-V12 路径上的 `validate decide`（示例见 feature-t5 一节）必须同时携带上述绑定参数（`--candidate-commit` 至 `--context-digest`），同一决定事实记录绑定，该路径的 push 许可为 ALLOW。

`publish dispatch` 以绑定构造 push 许可请求交 feature-t6 Policy Gate 评估；非 ALLOW 只留记录、不改条件、不做任何外部调用（退出码 1 或 2）。ALLOW 后开启 attempt、持有预约并登记执行描述；`publish run` 的执行以该 ALLOW 为触发把节点推进到 EXECUTING，复核任务分支、推送地址与平台仓库身份，按同一 operation 读远端任务分支，缺席或为候选祖先时以非强制、只含该一个 ref 的推送推到已核地址，随后识别唯一同源开放或已合并的 Pull Request，或以绑定标题、正文加 operation 尾行创建一个并回读。两者都确认后同一事务形成 COMPLETED 与 published 终态槽位，名额随之释放。

外部结果分为 published、not-happened、partial、uncontrolled-change 与 unknown，证据分列。除 published 以外节点进入 RECOVERY_REQUIRED；unknown 时预约保持、不能再派发。`publish query` 只读查询同一 operation：确认成功则经 RESTORE_PUBLISH_FINALIZATION 完成终态，不再推送或创建；确认未发生或部分完成则判为 RECONCILIATION_REQUIRED；查询不成判为 INDETERMINATE；非受控变化不形成判定并停报。`publish reconcile` 要求 Human 对 RECONCILE_CURRENT_NODE 与影响范围 `publish-operation:<operation id>` 的单次授权（`--human-authorization` JSON），重新评估 push 许可后以同一 operation 补做缺失步骤。Publish Authorization Gate 与 Publish 节点上的通用事实、推进、条件、attempt、预约、`publish-finalize`、`recover-assess` 与 `recover` 命令对任何任务以 `GENERIC_COMMAND_NARROWED` 拒绝，任意时点终止保留。平台程序由已登录的程序自行持有凭据，其路径、摘要与版本每次执行重新发现并记录，不作允许列表。

serve-stdio 另投影 capability `harness.publish`（action `publish.authorize`、`publish.dispatch`、`publish.query`、`publish.reconcile`），与 CLI 执行同一领域命令；reconcile 的 Human 授权取可信 Human 决定本身。逐 AC 离线验收报告：

```sh
apps/harness/.venv/bin/python apps/harness/tests/run_publish_report.py --output records/diagnostics/feature-t7/<日期>/<本轮目录>
```

报告逐条给出 AC-01 至 AC-09 的 PASS / FAIL / NOT_RUN、每个测试的合成产品线持久状态前后、本机 bare 远端 ref 与合成平台请求，ERROR 与 FAIL 分列；真实 GitHub 推送与 Pull Request、真实平台程序、GitLab、真实模型、J-03 bundle、J-04、J-05、J-06 真实 Host 联调与 J-07 保持 NOT_RUN。

## Runtime 开发 bundle（feature-t18）

面向 macOS/arm64 的自包含开发 bundle：包内携带固定的 CPython 3.12（python-build-standalone，身份见 `bundle/inputs.lock.json`）、按 `requirements.lock` 哈希锁定的依赖、hp 产品源码与产品运行期导入的评审通道模块；不含治理记录、任务契约、测试、开发环境或活体 Registry。它只声明已交付子集、来源与缺失能力（`bundle.json`），不是完整公开安装包；完整安装、升级、卸载、check/init/fix 与签名产品化归 M-05 后继任务。

构建只从精确提交与已固定摘要的输入进行，不下载；每个位置都是显式参数，没有指向任何机器目录的缺省值，缺参数按名拒绝：

```sh
apps/harness/.venv/bin/python -B apps/harness/bundle/build.py --repository <hp 仓> --source-commit <40 位提交> \
  --inputs-dir <构建输入目录> --runtime-id runtime:<名> --publisher-id publisher:<名> --source-reference <来源说明> \
  --signing-key <私钥文件> --publisher-key <publisher.pub> --openssl <OpenSSL 程序> \
  --identity-registry <身份登记 jsonl> --output <不存在的输出目录>
```

输出的 `bundle/` 目录恰为接收方导入的四件：`bundle.tar`（确定性 ustar）、`release.json`（发布记录）、`release.sig`（Ed25519 分离签名的十六进制）、`publisher.pub`；另有 `build-record.json`。同一提交与输入两次构建逐字节相同；版本号为 `0.1.0-dev.<提交前 12 位>`，身份登记拒绝同 runtimeId 同版本的不同字节。私钥只由 OpenSSL 子进程按给定路径读取，不进入本进程、参数、输出或任何写出的文件。

启动：入口 `python/bin/python3.12`，`direct` 启动器，argv 模板 `-I -B -m hp serve-stdio --bundle --runtime-root ${runtimeRoot} --instance-dir ${instanceDir} --contract-digest ${contractDigest}`，只用冻结闭集占位符，不用 `${resourceHandle}`，不读环境变量推导路径（`-I` 忽略 PYTHON* 变量，入口启动时移除七个仓库定位类 GIT_* 变量）。Runtime 启动时核对契约摘要参数，按 `bundle.json` 逐成员核对并以同一写出器重建 archive 得到自身真实摘要；Initialize 的 bundleDigest、launchAuthorization.bundleDigest 与 permissionProfileDigest 须等于自身值，否则 INTEGRITY_MISMATCH 且不进入 ready。

Manifest 的 `executionProfileRequirements` 声明三项可选能力依赖的执行 profile（只含 id、version 与策略 digest，不含程序身份）：`harness.definition` 与 `harness.validate-change` 依赖构建提交中 Registry 唯一 embedded 评审端口的 Reviewer profile，`harness.implement-verify` 依赖评审通道设计 §7.5 的 J-04 Implementer profile。Host 在 Initialize 的 `executionProfiles` 提供同一 id、version 与 digest 时该 profile 被选中、能力保留；未提供或 digest 不同时按 Contract 把对应能力从协商结果移除。Registry 中 embedded 评审端口不是恰好一个时构建拒绝。

仓与执行绑定只来自实例目录中的绑定文件 `hp-binding.json`，在接收机器上由 Human 以包内 CLI 写入：

```sh
<包目录>/python/bin/python3.12 -I -B -m hp binding write --instance-dir <实例目录> --repository <产品线仓绝对路径> \
  --resource-handle <Host 登记的资源句柄> [--execution-bindings '<按端口的 JSON>'|@<文件>] --authority-ref <授权定位> [--replace]
<包目录>/python/bin/python3.12 -I -B -m hp binding show --instance-dir <实例目录>
```

绑定文件缺失、无效或仓不可用时 Runtime 照常启动，health 为 degraded 并给出原因，不写领域状态；`runtime.scope.open` 只接受绑定文件列出的句柄，其余以 PERMISSION_DENIED 拒绝。写入后请 Host 重连实例生效。standalone CLI 以同一解释器运行（`<包目录>/python/bin/python3.12 -I -B -m hp <命令组> ...`），与 Runtime 经同一写者锁与控制代次竞争。

测试与逐 AC 报告需要显式给出构建输入目录与用于交叉验签的 OpenSSL 程序：

```sh
HP_BUNDLE_INPUTS_DIR=<构建输入目录> HP_BUNDLE_OPENSSL=<OpenSSL 程序> apps/harness/.venv/bin/python -m unittest discover -s apps/harness/tests -p 'test_bundle.py'
HP_BUNDLE_INPUTS_DIR=<构建输入目录> HP_BUNDLE_OPENSSL=<OpenSSL 程序> apps/harness/.venv/bin/python apps/harness/tests/run_bundle_report.py --output <本轮独立目录> [--delivery <交付构建输出目录>]
```

测试以被测代码和进程内临时生成、标注 SYNTHETIC 的密钥构建 bundle，由复现接收方准入与启动方式的合成 Host 驱动；它证明 hp 产物在该复现上成立，不代表接收方真实行为，Assistant supervisor 的真实启动与接收由 Assistant 侧执行。

## 已保留的后继范围

feature-t1 提供 hotfix 登记与来源解析；feature-t3 已交付 Define Task 与 Review Definition 环（见「Define Task 与 Review Definition（feature-t3）」一节），feature-t4 的 Implement / Verify 环见「Implement 与 Verify 环（feature-t4）」一节，feature-t5 的三处 autonomous budget 与 Validate Change 环见「Validate Change 环与 autonomous budget（feature-t5）」一节，feature-t7 的 Publish 与受控恢复见「Publish 与受控恢复（feature-t7）」一节（真实 GitHub 上的运行仍为 NOT_RUN）；以上都消费 feature-t2 交付的状态推进面，本节不预支它们的语义。feature-t6 的 Policy Gate 已交付，见「Policy Gate（feature-t6）」一节；其授权回调的生产注入由 feature-t3 接线，feature-t4 注入产品侧 Implementer 登记读取器，feature-t7 在派发时取 push-permit 结论并在 Publish 授权时写入 publishBinding。feature-t15 汇集实际治理日志与统一时间线；feature-t17 的执行接缝见下节，真实 J-04 仍须独立验收；feature-t18 交付 Runtime 开发 bundle（见上节），完整安装、升级、卸载与维护入口归 M-05 后继任务；feature-t19 完成 mars-homepage。当前十个 host.* 方法的管道测试只证明适配端编码、响应核对、超时和错误处理。没有真实模型调用、真实 Agent 会话、真实迁移/回退、断电耐久证明，也不声明 J-03 至 J-07 或 V-10/M-04 完成。

## 产品评审执行端口

feature-t17 的 `execution/` 提供可注入的异步 `HostExecutionPort`、`LocalExecutionPort` 和 `ProductReview`。`ProductReview.review(mode, options)` 在线程内调用正式评审 runner，物理 I/O 留在 Runtime 事件循环，报告与诊断写各自 sink，不写 Runtime stdout。维护 CLI 保持原入口与输出。生产 Domain Core 尚未安装时端口拒绝执行；不能把 tests/GitDomain 注册为生产实现。

可信领域调用方为每个 attempt 新建端口与 ProductReview，提供当前连接发现回调、授权回调和已知秘密扫描集。端口只允许一次扫描上下文绑定，第二次绑定在任何状态改变前拒绝；重新取得 Runtime generation 后可以用新端口实例查询原预约。发现结果分别绑定 Host connectionRef、hp Registry provider、协议 modelProvider 与配置修订，三个标识不作字符串等同。授权回调每次执行、查询、取消及恢复都重新检查 scope、Grant、DecisionRecord、作者固定来源和 Owner 授权；返回的 ExecutionAuthorization 不从 Request 或 invocation_authorization 反序列化。纯 Human 来源必须有固定证据，未知作者不能用空厂商集合替代。同一 authorization_ref 的物理调用数持久累计，格式补发也占用它的 max_calls。

先核当前完整 profile/程序身份和用途，再封存材料与预约。材料按 manifest 原字节、名称、次序和摘要导出 Runtime EvidenceRef，resourceHandle 保持已授予的绑定资源，objectRef/不可变 revision 区分材料；Domain 以完整 EvidenceRef 的规范摘要作为内部键，旧键读取仍必须逐字段等于请求证据，单独指令资源记录原 bundle_name 到 objectRef 的映射。Host context.capture 只接受 succeeded 且逐件身份一致的快照；异步或未知只查询原 operation。Host start 的请求身份在放行前保存；未知应答不重发。仅 BUSY/RESOURCE_LIMIT 且 recovery=retry-later 按原键原摘要有界重试，不把它解释成 absenceProven。

结果只由 Host.resource.read 获取，校验完整封套与 UTF-8 answer 两层 bytes/digest，以及 execution、operation、profile、模型和协议来源。原封套与回答归正式通道原件。端口在持久化前检查已知秘密的原字节和递归解码后的 JSON 字符串；这不代表检测所有未知秘密。取消先持久记录，不启动尚未放行的执行；完成、超时或取消不自动释放领域预约。

相同 PhysicalExecution 不重复追加观察。每个窗口最多256种连续变化的事实；满窗后保守失败并保留保护引用。可信调用方可以显式执行 `await port.checkpoint_observations(reservation)`，在当前领域事务内把满窗原字节保存为不可变 Runtime evidence，成功后才开启新窗口。原 start/operation/execution 身份不变，后续 query 仍查原执行；没有自动重启或释放。`historical_observations` 核对每个历史窗口的引用、字节数和摘要，桥接把窗口原件与引用放入既有 runtime_events.jsonl，资格读端检查缺失与篡改。

Local 使用独立 supervisor 和握手后放行，worker 在 adapter 可调用前核实际程序路径、文件摘要及版本。未能提供这些事实的 adapter 拒绝，不由旧版本推定能力。Local 如实记录 adapter-report 的模型来源；worker 退出不足以证明所有子进程退出，故观察保持 partial，pipesClosed 不合成 true，预约继续受保护。Implementer 的独立监督与领域结算见「Implement 与 Verify 环（feature-t4）」一节。

新增 Receipt v4 / effective Profile v4 / Registry v5 由机制读端按版本校验；Request 在 legacy-git 用 v4、archive-v1 用 v5。能力建议只由最终事实计算，写 Registry 与真实资格验收是独立阶段。当前真实 J-04 受 Assistant KB-245 及当次真实模型授权约束，合成测试不产生产品资格。

离线执行测试使用 `HP_EXECUTION_TEST_OUTPUT=/absolute/durable/directory` 保留归档原件，目录必须位于所有 Git worktree 外；无此变量时使用用户数据目录下独立测试目录。`test_execution_stdio.py` 经真实 Stdio、HostClient、Dispatcher、Runtime resource.read 和正式 runner，Host 与模型内容明确为合成。它补充 t16 的协议符合性，不能替代真实 Assistant/Codex 验收。
