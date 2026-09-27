# mars-assistant-harness-plane

[![CI](https://github.com/csthink/mars-assistant-harness-plane/actions/workflows/ci.yml/badge.svg)](https://github.com/csthink/mars-assistant-harness-plane/actions/workflows/ci.yml)

HarnessPlane（简称 hp）是面向 AI Coding Agent 的软件工程治理与编排控制平面。它不重新实现 Claude Code、Codex 等 Coding Agent，而是以 Task 为一级管理对象、以官方 Workflow 为治理骨架，让现成的 Agent 担任可评审、可审批、可追溯的 Executor 与 Reviewer；Human 保留最终决定权，Agent 只在 Human 授予的有限额度内自主推进。

## 本仓是什么

本仓是 hp 的**机制与运行时载体**，只包含三个目录树：`apps/`、`mechanisms/`、`.agents/`。这三棵树合称机制区，也就是 hp 安装到一个产品线仓时分发的载荷。

hp 治理的对象是**产品线仓**：由人建立并安装了 hp 的 Git 仓库。产品线仓的实例区（`sdd/` 规格链、`tasks/` 任务记录、`records/` 治理记录等）在产品线仓内，不在本仓。本仓自身不是产品线仓，所以这里没有实例区，也不对本仓运行 `mechanisms/gates/` 的布局与清单核对。

hp 可以经 Runtime Contract 0.1.0 被图形客户端连接，Assistant 的 macOS 客户端源码见 [mars-assistant-mac](https://github.com/csthink/mars-assistant-mac)。不连接客户端时，同一条领域旅程可以只用 standalone CLI 完成。

## 目录

| 路径 | 内容 |
| --- | --- |
| `apps/harness/` | 产品源码：入口 `hp.py`（standalone CLI 与 serve-stdio Runtime）、Domain Core、执行端口、Runtime 开发 bundle 构建工具、冻结的 Runtime Contract 0.1.0 副本（`contract/`）与产品测试（`tests/`）；详细命令见 [`apps/harness/README.md`](apps/harness/README.md) |
| `mechanisms/` | 八个机制单元，一单元一目录；单元与分发清单见 [`mechanisms/MECHANISMS.md`](mechanisms/MECHANISMS.md) |
| `.agents/skills/` | 随载荷分发的 Agent skill 正本：`cst-review`、`cst-ship`、`proposal-guide`、`verify-from-text` |
| `tools/` | 公开仓安全检查 `check-public-safety-generic.sh` 与 pre-commit hook 安装器 `install-hooks.sh` |
| `docs/architecture.md` | 架构说明：组件、依赖方向、状态与持久化、设计取舍 |
| `CONTRIBUTING.md` | 参与本仓开发：约束、本地检查、提交前扫描、改动检查清单 |

## 环境

- CPython 3.12，macOS arm64。`apps/harness/requirements.lock` 以 SHA-256 固定全部直接与传递依赖；其中 `rpds-py` 只登记了 CPython 3.12 macOS arm64 的 wheel，在其他平台上 `--require-hashes` 安装会失败。
- macOS 版本。`test_bundle` 中安装或启动 Runtime 开发 bundle 的用例要求本机 macOS 不低于 bundle manifest 的 `minimumOs`（`apps/harness/bundle/manifest.py` 的 `MINIMUM_OS`），与接收方准入的判定相同；低于时这些用例以 `host macOS <版本> is below the bundle minimumOs <版本>` 为原因 skip，其余用例照常运行。
- Git。Domain Core 的正式状态保存在被治理仓库的 Git 对象里，测试也在临时目录中创建合成 Git 仓。
- 依赖装在仓内独立的虚拟环境 `apps/harness/.venv/`（已被忽略），不修改全局 Python；Runtime 启动时不下载任何东西。

## 快速开始

```bash
git clone https://github.com/csthink/mars-assistant-harness-plane.git
cd mars-assistant-harness-plane
./tools/install-hooks.sh

python3.12 -m venv apps/harness/.venv
apps/harness/.venv/bin/python -m pip install --require-hashes -r apps/harness/requirements.lock
```

`hp.py` 按第一个参数分派：

| 第一个参数 | 作用 |
| --- | --- |
| `serve-stdio` | Runtime 入口：经 stdio 与 Host 连接，实现 Runtime Contract 0.1.0 |
| `task`、`config`、`workflow`、`definition`、`policy`、`implement`、`verify`、`budget`、`validate`、`publish` | standalone CLI 命令组，与 serve-stdio 调用同一个 Domain Core |
| `binding` | 为 Runtime 开发 bundle 写入或查看实例绑定文件 |

每个命令组都有 `--help`，例如：

```bash
apps/harness/.venv/bin/python -B apps/harness/hp.py task --help
apps/harness/.venv/bin/python -B apps/harness/hp.py workflow --help
```

standalone CLI 的命令以 `--repository <产品线仓>` 指定被治理的仓库。serve-stdio 由启动方给出启动配置与仓库：

```bash
apps/harness/.venv/bin/python apps/harness/hp.py serve-stdio --launch-config <启动配置 JSON 的绝对路径> --repository <产品线仓的绝对路径>
```

没有给出仓库或仓库不可用时 Runtime 仍然启动，但 `runtime.health` 返回 `degraded` 并给出原因，不假装领域已就绪。

## 测试

以下命令都在仓根运行。它们不调用真实模型、不需要任何凭据、不写真实远端：领域事实、Host、Agent、评审方与平台程序都是标注为合成的测试替身。

**产品测试**（完整套件耗时以数十分钟计）：

```bash
apps/harness/.venv/bin/python -B -m unittest discover -s apps/harness/tests -p 'test_*.py'
```

**Runtime Contract 符合性报告**：再完整运行一次同一套件，并逐帧核对 Runtime 发出的协议帧符合冻结 schema。`--output` 必须是尚不存在的目录，取较短的路径（用例会在其中登记合成 Agent 的命令路径，长度有上限），并放在仓外：

```bash
apps/harness/.venv/bin/python -B apps/harness/tests/run_contract_conformance.py --output <仓外尚不存在的短路径目录>
```

**机制单元 selftest**：

```bash
apps/harness/.venv/bin/python -B mechanisms/artifact-templates/artifact_lint_selftest.py
apps/harness/.venv/bin/python -B mechanisms/delivery-method/run_delivery_method_reminder_selftest.py
apps/harness/.venv/bin/python -B mechanisms/gates/gates.py selftest
apps/harness/.venv/bin/python -B mechanisms/handoff-protocol/handoff_selftest.py
apps/harness/.venv/bin/python -B mechanisms/handoff-protocol/handoff_cl56_selftest.py
apps/harness/.venv/bin/python -B mechanisms/handoff-protocol/handoff_cl57_selftest.py
apps/harness/.venv/bin/python -B mechanisms/handoff-protocol/handoff_workflow_selftest.py
apps/harness/.venv/bin/python -B mechanisms/repo-layout/history_read_selftest.py
apps/harness/.venv/bin/python -B -E -s -S -X pycache_prefix="$(mktemp -d)" mechanisms/review-channel/review_channel.py selftest
```

评审通道只接受净化启动（`-B -E -s -S -X pycache_prefix=<已存在的目录>`），最后一条因此与其他几条写法不同。`gates.py selftest` 在隔离的临时仓里运行，不对本仓做布局或清单核对。

**测试用的环境变量**：

| 变量 | 作用 | 未设置时 |
| --- | --- | --- |
| `HP_BUNDLE_INPUTS_DIR` | Runtime 开发 bundle 的构建输入目录：按 `apps/harness/bundle/inputs.lock.json` 的布局存放固定摘要的解释器资产（`<目录>/python-build-standalone/<releaseTag>/<asset>`）与 `requirements.lock` 所列 wheel（`<目录>/wheels/`） | `test_bundle` 的用例报 ERROR 并写明缺少该变量；这是有意的显式失败，不是 skip |
| `HP_BUNDLE_OPENSSL` | 用于交叉验签的 OpenSSL 3 程序（系统自带的 LibreSSL 不支持该用法） | 交叉验签用例报 ERROR 并写明缺少该变量 |
| `HARNESS_INSTANCE_ROOT` | 少数产品测试、`artifact_lint_selftest.py` 的实例模式正例与四个报告生成器（`run_bundle_report.py`、`run_implement_verify_report.py`、`run_publish_report.py`、`run_validation_report.py`）以某个产品线仓实例区里的固定文件作输入；本变量指向实例区的根目录，即 `sdd/`、`tasks/` 所在的目录。这些文件只读不写 | 依赖它的用例以 `HARNESS_INSTANCE_ROOT is not set` 为原因 skip，`artifact_lint_selftest.py` 把实例模式正例逐条记为跳过，报告生成器拒绝运行；其余用例照常运行 |
| `HARNESS_INSTANCE_RECORDS` | 实例区 `records/` 树所在的目录，供 `records/` 不在实例区根目录下的布局使用；实例区路径以 `records/` 开头的文件从这里读取，其余从 `HARNESS_INSTANCE_ROOT` 读取 | 取 `$HARNESS_INSTANCE_ROOT/records`，即产品线仓内的布局 |
| `HP_EXECUTION_TEST_OUTPUT` | 执行端口离线测试保留归档原件的耐久目录，须在所有 Git worktree 之外，也不能在系统临时目录（`/tmp`、`/private/tmp`、`/var/tmp`、`/private/var/folders`、`/dev/shm`）之下，否则评审归档以 `temporary archive root forbidden` 拒绝 | 使用家目录下的独立测试目录，并在用例结束后清理 |
| `HP_TEST_TIMEOUT_SCALE` | 测试 Host 驱动各项等待预算的放大倍数，供较慢的机器使用 | 倍数为 1 |

准备 `HP_BUNDLE_INPUTS_DIR` 时，解释器资产按 `inputs.lock.json` 的 `url` 下载后核对 `bytes` 与 `sha256`，wheel 用下面的命令按锁定的散列下载；构建器本身只从该目录读取，从不下载：

```bash
apps/harness/.venv/bin/python -m pip download --require-hashes --no-deps --only-binary=:all: -r apps/harness/requirements.lock -d <构建输入目录>/wheels
```

**公开仓安全检查**：

```bash
./tools/check-public-safety-generic.sh
```

## 持续集成

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) 在 push 到 `main` 与目标为 `main` 的 pull request 上运行，只有一个 job，名为 `verify`：

1. 公开仓安全检查：先跑扫描器自身的阳性对照 `--selftest`，再扫描本仓已跟踪的全部内容。CI 与 pre-commit hook 调用的是同一个文件。
2. 在 macOS arm64 runner（`macos-26`）上安装 CPython 3.12，按 `requirements.lock` 带散列安装依赖。
3. 准备 Runtime 开发 bundle 的构建输入（固定摘要的解释器资产与 wheel）和 OpenSSL 3。
4. 产品测试、Runtime Contract 符合性报告、全部机制单元 selftest。

CI 不设置 `HARNESS_INSTANCE_ROOT` 与 `HARNESS_INSTANCE_RECORDS`，不调用真实模型，不引用任何 secret，token 权限只有 `contents: read`。测试报告只写在 runner 的临时目录里，不作为 artifact 上传。

runner 镜像的 macOS 低于 bundle 的 `minimumOs` 时，产品测试与符合性报告中安装或启动 bundle 的用例以 `host macOS <版本> is below the bundle minimumOs <版本>` 为原因 skip（见「环境」）。这部分覆盖只在满足该版本的机器上取得，由维护者在本机运行完整套件并留存验证记录。

## 文档

- [docs/architecture.md](docs/architecture.md)：组件、依赖方向、状态与持久化、设计取舍
- [CONTRIBUTING.md](CONTRIBUTING.md)：参与本仓开发
- [apps/harness/README.md](apps/harness/README.md)：standalone CLI 与 Runtime 的完整命令与语义
- [mechanisms/MECHANISMS.md](mechanisms/MECHANISMS.md)：机制单元花名册与分发清单；各单元的设计正本在各自目录内

## 许可

本仓暂未授予开源许可，不附 `LICENSE` 文件。源码公开可读；在另行声明之前，不授予复制、修改或再分发的许可。
