# 贡献指南

本仓是 HarnessPlane（hp）的机制与运行时载体，只包含 `apps/`、`mechanisms/`、`.agents/` 三个目录树，也就是 hp 安装到产品线仓时分发的载荷。产品线仓的实例区（`sdd/`、`tasks/`、`records/` 等）不在本仓。

这份文档说明改本仓时必须守住的约束，以及改动怎么验证。

## 开始之前

克隆后先装 pre-commit hook（幂等，只需一次）：

```bash
./tools/install-hooks.sh
```

然后按 [README](README.md)「快速开始」建立 `apps/harness/.venv/` 并安装锁定的依赖。环境要求是 CPython 3.12 与 macOS arm64：`apps/harness/requirements.lock` 只登记了这一平台的二进制 wheel 散列。

## 硬性约束

下面几条破坏后会造成运行失败或结构性返工，改代码前先确认：

| 约束 | 理由 |
| --- | --- |
| `apps/` 与 `mechanisms/` 保持在同一仓、相对位置不变，机制文件的路径视为载荷接口 | 执行层与 Policy Gate 按源码相对位置导入 `mechanisms/review-channel/` 的模块；领域命令另从被治理的产品线仓读取已安装载荷里的同名路径：Workflow 拓扑 `mechanisms/delivery-method/MVP_Workflow_v5.drawio`、Definition 结构门 `mechanisms/artifact-templates/artifact_lint.py`、评审通道 Registry `mechanisms/review-channel/review_channel_registry.json`。移动或改名这些文件，就是改变产品线仓必须满足的布局 |
| Workflow 拓扑只在 `MVP_Workflow_v5.drawio` 定义，代码只读 | 拓扑是 Workflow 的语义权威；Domain Core 从中取稳定的节点与边身份，不在代码里新增节点、边或 Gate |
| `apps/harness/contract/schema.json` 与 `methods.json` 保持原字节 | 它们是冻结的 Runtime Contract 0.1.0 的副本，协议身份以原字节摘要为准；Contract 的任何变化都要以新版本出现，不在本地改写 |
| Domain Core 是 Workflow 状态推进的唯一写者 | standalone CLI 与 serve-stdio 是同一个 Domain Core 的两个调用面，共用写者锁、控制代次与正式状态；不为某个入口另建状态机 |
| 依赖只经 `apps/harness/requirements.lock` 引入，每项带 SHA-256 | Runtime 启动时不下载；`apps/harness/bundle/inputs.lock.json` 的 wheel 身份就是该锁文件的散列，两者须一致 |
| 测试不调用真实模型、不使用真实凭据、不写真实远端 | 测试里的 Host、Agent、评审方与平台程序都是合成替身并如实标注；测试用的产品线仓必须带 `.synthetic-hp-domain` 标记，测试启动器拒绝未标记的仓 |
| 测试记录不进本仓 | 报告生成器与符合性报告的 `--output` 放在仓外；路径门拦截 `records/`、任意层级的 `attempts/`、`report.json`、`receipt.json`、`playwright*.json`、`*.tap` |
| `mechanisms/MECHANISMS.md` 不手改 | 它是 `mechanisms/gates/` 清单生成器的输出（文件头标注 `auto-generated: true`）；本仓不是产品线仓，不对本仓运行 `gates.py layout` 与 `gates.py manifest`，生成源文件保留给安装了 hp 的产品线仓使用 |
| 不为「以后可能用」提前加抽象或组件 | 能力范围由已定义的 Workflow 与 Runtime Contract 限定 |

## 本地检查

提交前至少跑与改动相关的部分；改到 `apps/harness/` 时跑完整产品测试，改到某个机制单元时跑该单元的 selftest。命令都在仓根运行：

```bash
# 产品测试
apps/harness/.venv/bin/python -B -m unittest discover -s apps/harness/tests -p 'test_*.py'

# Runtime Contract 符合性报告（再运行一次完整套件并核对协议帧）；--output 取仓外尚不存在的短路径目录
apps/harness/.venv/bin/python -B apps/harness/tests/run_contract_conformance.py --output <仓外尚不存在的短路径目录>

# 机制单元 selftest（完整列表见 README「测试」一节）
apps/harness/.venv/bin/python -B mechanisms/gates/gates.py selftest
apps/harness/.venv/bin/python -B -E -s -S -X pycache_prefix="$(mktemp -d)" mechanisms/review-channel/review_channel.py selftest

# 公开仓安全检查
./tools/check-public-safety-generic.sh
```

完整产品测试包含 Runtime 开发 bundle 的用例，需要 `HP_BUNDLE_INPUTS_DIR` 与 `HP_BUNDLE_OPENSSL` 两个环境变量；缺少时这些用例报 ERROR 并写明变量名。准备方法见 README「测试」一节。依赖某个产品线仓实例区的少数用例在 `HARNESS_INSTANCE_ROOT` 未设置时以明确原因 skip，CI 也不设置它。

## 改动检查清单

| 改动类型 | 必须说明或验证 |
| --- | --- |
| Runtime 协议（`apps/harness/runtime/protocol.py`、`transport.py`、`dispatcher.py`、`host.py`） | 冻结 Contract 副本未变；符合性报告通过，Runtime 发出的帧全部符合 schema |
| Workflow 状态推进（`apps/harness/domain/workflow/`） | 状态组合仍落在合法矩阵内；拓扑文件零改动；每次状态改变仍是同一事务内的一次 Progression Commit |
| 领域命令（`apps/harness/domain/` 其余子包与 `apps/harness/cli/`） | CLI 与 Runtime action 仍调用同一个领域命令；结果码闭集与退出码的变化写进 `apps/harness/README.md` |
| 执行端口（`apps/harness/execution/`） | 嵌入模式不二次启动 Agent；程序身份每次执行重新发现并记录；取消、超时与未知结果不自动释放预约 |
| Policy Gate（`apps/harness/domain/policy/`） | 仍是 Policy Decision 的唯一产生点；输入缺失、不可读或身份不符时不产生 ALLOW |
| Runtime 开发 bundle（`apps/harness/bundle/`、`apps/harness/runtime/launch.py`） | 带 `HP_BUNDLE_INPUTS_DIR` 与 `HP_BUNDLE_OPENSSL` 运行 `test_bundle` 通过；同一提交与输入两次构建逐字节相同 |
| 机制单元（`mechanisms/<单元>/`） | 该单元的 selftest 通过；行为变化同步到单元目录内的设计正本 |
| Agent skill（`.agents/skills/`） | 只改中立正本；各家 Agent 的专属目录只做加载，不另存副本 |
| 依赖（`apps/harness/requirements.lock`） | 每项带散列；`inputs.lock.json` 的 wheel 身份同步；完整产品测试通过 |
| 公开文档（`README.md`、`CONTRIBUTING.md`、`docs/`） | 目录、命令与环境变量和仓内实际一致 |

## 提交前

本仓是**公开仓**。提交前请确认改动里没有夹带不该公开的内容：内部主机名、内网地址、本机绝对路径、个人信息、真实凭据、内部计划，或未公开的评审结论。

pre-commit hook 只检查本次暂存的文件，内容从索引读取，调用的是 `tools/check-public-safety-generic.sh`，覆盖凭据字面量、私钥、云平台凭据形态、本机路径、内网地址五类内容，另加一道路径门（测试记录与证据的路径）。CI 对全部已跟踪内容再跑同一个文件。

测试里需要凭据形态的合成值时，把它登记进与扫描器同目录的白名单 `tools/public-safety-allowlist.txt`：每行一个扩展正则，对「相对路径:行内容」整体匹配，规则带路径前缀限定范围。路径门不受白名单影响。

hook 可以被 `git commit --no-verify` 绕过，CI 是第二道。**内容一旦 push 出去，即使后续删除也仍留在 Git 历史里**，所以提交前请自己再过一遍。

提交信息只描述改动本身。
