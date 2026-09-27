---
auto-generated: true
generator: manifest --write
source: mechanisms/gates/mechanisms_source.md
---

# 机制单元花名册（MECHANISMS）

> 本文件是**单元花名册与分发清单**：列出 `mechanisms/` 下的全部机制单元，以及本仓对安装载荷的贡献。
>
> 只指路。单元目录文法、花名册完备性核对要求与载荷边界的规则，一律见 `mechanisms/repo-layout/HarnessPlane_Repo_Layout_Design_v1.md`，本文件不复述、不承载状态。

## 单元表

下表由磁盘发现的单元目录派生（`manifest --write` 生成；核对 = 人工可选 `manifest`）。

| 单元 | 目录 | 设计正本 | 可执行物 |
|---|---|---|---|
| `artifact-templates` | `mechanisms/artifact-templates/` | 无 | `artifact_lint.py`（selftest：`artifact_lint_selftest.py`） |
| `decision-mechanism` | `mechanisms/decision-mechanism/` | `HarnessPlane_Decision_Mechanism_Design_v1.md` | 无 |
| `delivery-method` | `mechanisms/delivery-method/` | `HarnessPlane_Delivery_Method_Design_v1.md` | `run_delivery_method_reminder.py`（selftest：`run_delivery_method_reminder_selftest.py`） |
| `freeze-record` | `mechanisms/freeze-record/` | `HarnessPlane_Freeze_Record_Design_v1.md` | 无 |
| `gates` | `mechanisms/gates/` | `HarnessPlane_Gates_Design_v1.md` | `gates.py`（selftest：`selftest.py`）、`gates_base.py`、`gates_generate.py`、`gates_layout.py`（selftest：`selftest_layout.py`）、`gates_manifest.py`（selftest：`selftest_manifest.py`） |
| `handoff-protocol` | `mechanisms/handoff-protocol/` | `HarnessPlane_Handoff_Protocol_Design_v1.md` | `github_pr_api.py`、`handoff_cl56_selftest.py`、`handoff_cl57_selftest.py`、`handoff_data.py`、`handoff_lint.py`、`handoff_migration.py`、`handoff_platform.py`、`handoff_selftest.py`、`handoff_status.py`、`handoff_workflow.py`（selftest：`handoff_workflow_selftest.py`） |
| `repo-layout` | `mechanisms/repo-layout/` | `HarnessPlane_Repo_Layout_Design_v1.md` | `history_read.py`（selftest：`history_read_selftest.py`） |
| `review-channel` | `mechanisms/review-channel/` | `HarnessPlane_Review_Channel_Design_v1.md` | `review_archive_migration.py`、`review_channel.py`（selftest：`review_channel_selftest.py`）、`review_channel_base.py`、`review_channel_contract.py`、`review_channel_decisions.py`、`review_channel_execution.py`、`review_channel_history.py`、`review_channel_inputs.py`、`review_channel_instruction.py`、`review_channel_receipt.py`、`review_channel_registry.py`、`review_channel_request.py`、`review_channel_runtime.py`、`review_channel_secrets.py`、`review_channel_selection.py`、`review_channel_selftest_archive.py`、`review_channel_selftest_base.py`、`review_channel_selftest_channel.py`、`review_channel_selftest_contract.py`、`review_channel_selftest_decisions.py`、`review_channel_selftest_inputs.py`、`review_channel_selftest_instruction.py`、`review_channel_selftest_receipt.py`、`review_channel_selftest_registry.py`、`review_channel_selftest_request.py`、`review_channel_selftest_secrets.py`、`review_channel_selftest_selection.py`、`review_channel_selftest_taskbook.py`、`review_channel_selftest_verdict.py`、`review_channel_taskbook.py`、`review_channel_verdict.py`、`review_evidence.py` |

## 分发清单

本仓对安装载荷的贡献 = 机制区三个整树，按目录取整：`mechanisms/` · `.agents/` · `apps/`。

实例区与证据区严禁入包。载荷的组装方式与载体形态由 gov-t13 分发设计裁定。
