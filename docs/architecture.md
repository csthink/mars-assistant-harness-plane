# 架构说明

本文说明 HarnessPlane（hp）的组件划分、依赖方向、领域状态的持久化方式与主要设计取舍。命令与参数的完整说明见 [`apps/harness/README.md`](../apps/harness/README.md)，各机制单元的规则以单元目录内的设计正本为准。

## 目标

AI Coding Agent 已经能理解、修改、测试和评审代码，缺的是其上的工程控制层：当前在做哪个 Task、该走什么流程、谁实现、谁评审、谁批准、哪些步骤可以自动推进、哪些必须由 Human 裁定、什么证据能证明某一步确实完成。hp 提供这一层，并遵守两条边界：

- 不重新实现 Coding Agent。Claude Code、Codex 等现成 Agent 担任 Executor 与 Reviewer，hp 负责派发、核对、记录与推进。
- Human 保留最终决定权。Agent 只在 Human 授予的有限额度（autonomous budget）内自主推进，额度用尽即回到 Human。

## 机制区与实例区

hp 把一个受治理的仓库分成两类内容：

| 分区 | 内容 | 所在位置 |
| --- | --- | --- |
| 机制区 | `apps/`（产品源码）、`mechanisms/`（机制单元）、`.agents/`（Agent skill 正本） | 本仓；安装时作为载荷分发到产品线仓 |
| 实例区 | `sdd/`（proposal、spec、milestones 规格链）、`tasks/`（任务记录与裁定）、`records/`（治理记录）等 | 各个产品线仓 |

产品线仓是由人建立并安装了 hp 的 Git 仓库，承载一条产品线从 proposal 到任务交付的全部正式记录。本仓只发布机制区，所以本仓不是产品线仓：这里没有实例区，也不对本仓运行面向产品线仓的布局与清单核对。

`apps/` 与 `mechanisms/` 必须同仓：执行层与 Policy Gate 按源码相对位置导入评审通道的模块；领域命令还要从被治理的产品线仓读取已安装载荷中的机制文件，包括 Workflow 拓扑、Definition 结构门使用的 `artifact_lint.py` 和评审通道 Registry。

## 端到端旅程

hp 覆盖一条产品线从意图到交付的四段旅程：

```text
前置    由人建立（或选择）产品线仓并安装 hp
Stage 0 Proposal 引导创作：按 proposal 模板产出 proposal.md，评审后定稿
Stage 1 spec.md 生产：起草、跨模型提供方评审、Human 定稿
Stage 2 milestones.md 生产：同上；任务在任务名单中出生
Stage 3 任务滚动开发：按官方 Workflow 从 Human Define Task 走到 Publish
```

Stage 3 的 Workflow 拓扑是 `mechanisms/delivery-method/MVP_Workflow_v5.drawio`，它是 Workflow 的语义权威：

```text
Human Define Task → Review Definition（可关）→ Frozen Task Definition → Implement
  → Verify（存在适用检查即执行）→ Validate Change（可关）→ Human Gate → Publish
```

拓扑内含三处 autonomous budget 循环（Definition 重审、Verify 修复、Validate Change 修复）。拓扑冻结，Review Definition 与 Validate Change 两个评审开关是唯一合法的裁剪；Verify 的 FAIL 不能带保留意见绕过。Human Gate 的合法决定由它在拓扑中的位置决定，例如定义授权门的 Authorize & Freeze、升级门的 Continue 与 Close Task、最终的 Publish 授权。

## 组件

| 组件 | 代码位置 | 职责 | 不做的事 |
| --- | --- | --- | --- |
| Domain Core | `apps/harness/domain/` | 来源核验与 Task 接纳、Workflow 状态推进、合法动作推导、Human 决定、Policy Gate、正式 Git 提交；是 Workflow 状态推进的唯一领域写者 | 不把 Host 的观察当作领域决定，不绕过 Human 权限 |
| standalone CLI | `apps/harness/cli/`，入口 `apps/harness/hp.py` | 把命令映射到 Domain Core 的领域命令，协调独立模式的执行端口 | 不绕过与 serve-stdio 共用的写者锁与预约 |
| serve-stdio Runtime | `apps/harness/runtime/` | 实现 Runtime Contract 0.1.0：协商、scope 授权、snapshot 与事件、action 与 operation、对 Host 的反向调用 | 不维护另一套状态机；嵌入模式下不二次启动 Agent |
| 执行端口（ExecutionPort） | `apps/harness/execution/` | 启动并观察 Agent 的物理执行：嵌入模式由 Host 实现、hp 侧为 `HostExecutionPort`，独立模式由 `LocalExecutionPort` 与独立监督程序实现，两者语义与结果结构相同 | 不修改领域正式记录；不把取消应答当作物理终态 |
| Review Channel | `mechanisms/review-channel/` | 受治理评审的唯一发起通道：材料封存、端口资格与厂商集合核对、判词结构的机械校验、归档与 Receipt | 不从 Host 文本取得授权；不把未知或取消当作评审 FAIL |
| Runtime 开发 bundle 构建工具 | `apps/harness/bundle/` | 从精确提交与固定摘要的输入确定性地构建可启动的 Runtime 开发包，并做分离签名 | 不是产品命令；构建时不下载；不等于完整的公开安装包 |

Assistant 的 macOS 客户端（[mars-assistant-mac](https://github.com/csthink/mars-assistant-mac)）承担 Runtime Host 职责：安装准入、权限与 Grant、物理执行身份、人工操作与展示。它只向 Runtime 请求领域 action，不写 hp 的 Workflow、任务或证据；hp 也不替 Host 判断物理执行事实。

## 包结构与依赖方向

```text
          hp.py（按第一个参数分派）
            │
    ┌───────┴───────────┐
    ▼                   ▼
  cli/            runtime/main.py · dispatcher.py · transport.py · host.py · launch.py
    │                   │         runtime/executions.py（执行描述调度、生产端口工厂）
    └─────────┬─────────┘
              ▼
          domain/core.py ── Domain Core 与唯一命令执行点 apply_command
              │
   ┌──────────┼───────────────────────────────┐
   ▼          ▼                               ▼
 domain/<子包>（acceptance · workflow ·   domain/store.py（持久适配、写者锁、
 definition · policy · implement_verify ·   控制代次、CAS 提交、漂移判定）
 budget · validation · publish）
   │
   ▼
 execution/（端口接口、Host 端口、Local 端口与监督程序、评审桥接）──▶ mechanisms/review-channel/

 runtime/protocol.py：冻结 schema 与方法表、严格帧解码、规范编码与错误类型，被以上各层共用
 domain/port.py：领域单一事务接口，不依赖 Host、Runtime 或 JSON Schema
```

- 两个入口（`cli/` 与 `runtime/`）只向下调用 Domain Core；没有模块反向依赖 `cli/`。
- `domain/` 在 Runtime 一侧只依赖 `runtime/protocol.py` 这一个模块，不依赖 dispatcher、transport 或 CLI；另依赖 `execution/` 的端口接口与评审桥接，`domain/policy/` 读取评审通道 Registry 时直接导入 `mechanisms/review-channel/` 的模块。
- 需要事务外效果的领域命令（启动评审、启动实施、推送与创建 Pull Request）只登记执行描述；执行层在接受 operation 之后调度它，完成后在新的领域事务里结算。进程重启后，对仍在运行的描述只查询同一请求，不重新执行。
- `bundle/` 是发布方工具，产品运行时不导入它。

## 领域状态与持久化

hp 的正式状态保存在被治理的产品线仓里，不另设数据库或常驻服务：

- 领域状态提交在 `refs/harness/runtime` 引用下；每次状态改变是同一事务内的一次 Progression Commit，依次核对期望的 Runtime Version、trigger 属于当前位置且未被消费、所选边从当前节点出发且目标落在合法组合内，然后写入记录、绑定 trigger 的消费、更新快照与版本。
- 两个入口的协调面在 `<git-common-dir>/harness/` 下：`writer.lock`（写者锁）、`bootstrap.json` 与 `binding.json`。每个改变状态的命令先取得控制代次再写，仍持旧代次的另一入口会被拒绝。
- 独立模式的物理执行观察写在 `<git-common-dir>/harness/executions/<executionRequestId>/`，只由监督程序写入。
- Workflow 的正式状态分五层，互不混用：Workflow 生命周期、当前位置（绑定的拓扑修订、稳定节点身份与本次进入的序号）、执行条件、Attempt 与 Progression Commit。组合必须落在按节点语义类型分列的合法矩阵内。
- 外部改动、文件缺失或身份不明一律判为漂移或未知并停报，不自动回滚，也不换请求身份重试。写者锁是合作入口之间的协议，不阻止同一账户下的其他程序直接改仓库；这类改动由漂移判定固定事实。

## Runtime Contract

- hp 实现的是冻结的 Runtime Contract 0.1.0。`apps/harness/contract/schema.json` 与 `methods.json` 是它的原字节副本，保留上游文件内的版本标记 `0.1.0-draft.5`，不改写；协议身份以契约摘要为准，常量在 `apps/harness/runtime/protocol.py`。
- capability schema 由安装方显式提供本地 Registry，登记摘要采用该 schema 的 RFC 8785 规范字节的 SHA-256；未知引用、网络与任意文件检索一律拒绝，没有从请求获取 schema 的入口。
- 合法动作集合由当前领域状态推导，dispatcher 在提交前重新取得 action，禁用或已变化即拒绝，因此界面不能创造权限。需要 Human 决定的 action 在 capability 中声明，dispatcher 先核对 Grant 与可信的决定记录，再接受 operation。
- operation 按请求身份幂等：同一请求重试得到同一结果或续完同一 operation，同一身份携带不同意图时以冲突拒绝。

## 执行、评审与 Policy Gate

- 执行端口先核对用途、模型、执行 profile 与实际安装的程序，持久记录预约之后才放行。程序身份每次执行重新发现并记入执行记录，Agent 或平台命令行程序的版本变化本身不导致拒绝。
- 同一请求只对应一次物理执行；应答丢失时查询原请求，不重发。取消是异步的，要核对到物理终态；完成、超时或取消都不自动释放领域预约，只有指名同一执行事实的结算才释放。
- Policy Gate 是 Policy Decision 的唯一产生点。它对固定闭集的判定项做 fail-closed 评估：任一适用项 FAIL 为 DENY，无 FAIL 而有未核对项为 NOT_DETERMINABLE，只有全部通过才是 ALLOW；输入缺失、不可读、身份不符或来源不可信都不产生 ALLOW。执行端口、评审通道与各环自身的核对保留为纵深防御，它们可以更严，但不能在 Policy Gate 未允许时放行。
- 评审只经 Review Channel 发起。作者的厂商集合与评审方的厂商必须满足跨模型提供方的要求，缺失即拒绝；业务上的评审 FAIL 是可消费的正式结果，沿拓扑的 FAIL 边继续，执行失败与结果不确定则进入恢复条件，不消耗额度。
- Publish 只在 Human 对精确候选提交与目标显式授权之后执行，止于推送远端任务分支并创建或识别 Pull Request。hp 没有合并、关闭 Pull Request 或删除分支的动作；发布授权、实际发布、合并与关闭是各自独立的事实。

## Runtime 开发 bundle

- 面向 macOS arm64 的自包含开发包：内含固定的 CPython 3.12（身份见 `apps/harness/bundle/inputs.lock.json`）、按 `requirements.lock` 散列锁定的依赖、hp 产品源码与运行期导入的评审通道模块；不含实例区内容、测试、开发环境或活体 Registry。
- 构建只从精确提交与已固定摘要的输入进行，不下载；每个位置都是显式参数，没有指向某台机器目录的缺省值。同一提交与输入两次构建逐字节相同。
- 发布记录用 Ed25519 分离签名，签名由 OpenSSL 子进程按给定路径读取私钥完成，私钥不进入构建进程、参数或任何输出。
- Runtime 启动时核对契约摘要参数，按包内描述逐成员核对并重建归档得到自身摘要；Host 在初始化时给出的包摘要须与之相等，否则不进入 ready。仓库与执行绑定只来自实例目录中的绑定文件，由 Human 用 `hp.py binding write` 写入。
- 开发 bundle 只声明已交付的子集与缺失的能力，不等于完整的公开安装包。

## 机制单元

| 单元 | 内容 |
| --- | --- |
| `artifact-templates` | proposal、spec、milestones、task、ruling、design 的模板，以及对前五类工件的可选一致性核对 `artifact_lint.py` |
| `decision-mechanism` | 公共技术 Decision 机制的设计 |
| `delivery-method` | 滚动交付方法的设计、方法全图、Stage 3 Workflow 拓扑 `MVP_Workflow_v5.drawio` 与规划基线修正提醒器 |
| `freeze-record` | 冻结记录的物理形制设计 |
| `gates` | 面向产品线仓的 layout 与 manifest 可选一致性工具，以及根 README 与单元花名册的生成器 |
| `handoff-protocol` | 会话交接与执行记录协议的设计与工具：进度文件文法核对、状态现算、交付工作流与 GitHub Pull Request 入口 |
| `repo-layout` | 仓库布局参考设计（机制区与实例区、目录文法、证据分层、载荷边界）与历史读取器 |
| `review-channel` | 跨模型提供方评审通道 |

每个单元一个目录，设计正本与可执行物同在；带 selftest 的可执行物见 [`mechanisms/MECHANISMS.md`](../mechanisms/MECHANISMS.md)。门与工具以「可执行物加退出码」提供，任何能运行 shell 的 Agent、CI 或人都能触发并得到同一结论。

## 信任边界

hp 在当前 macOS 用户账户内运行，受信任的本地 Agent 在指定的任务工作树里用其原生工具改代码。hp 的进程分离是职责与身份边界，不是操作系统隔离；执行 profile 与 Policy Gate 记录的是声明的执行边界与实际发生的事实，hp 不声称能机械阻断 Agent 在该账户内的任意操作。

## 设计取舍

| 取舍 | 理由 |
| --- | --- |
| 正式状态放在被治理仓库的 Git 对象里，而不是数据库或常驻服务 | 规格、决定与状态同处一处、可审计、可随仓库迁移；hp 不需要另设数据库或常驻服务 |
| 两个入口共用一个 Domain Core 与写者锁，而不是各建状态机 | 两套状态机会对同一事实给出不同的正式结果 |
| Workflow 拓扑冻结在一个文件里，代码只读 | 流程语义只有一个权威来源；代码不能悄悄增加节点或放宽 Gate |
| 程序身份每次执行重新发现，不按版本允许列表放行 | Agent 与平台程序升级频繁；按版本失效会误伤全部兼容能力，重新发现并记录更能如实反映实际执行 |
| 结果不确定时停报，而不是重试或回滚 | 重复执行或回滚都可能产生第二次外部效果；停报把判断留给 Human |
| 测试以真实 stdio 协议进程运行，领域事实与 Host 以标注的合成输入提供 | 协议路径是真实的，合成部分可以完整复现拒绝、中断与恢复路径 |
| Runtime 开发 bundle 构建不下载、不设缺省位置 | 构建结果只由提交与固定摘要的输入决定，可以逐字节复现 |
