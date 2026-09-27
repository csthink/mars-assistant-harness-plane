"""feature-t5: the three autonomous budgets of MVP_Workflow_v5 (spec FR-25).

Definition Review re-review, Verify remediation and Validate Change remediation each carry an explicitly
configured count budget. The budget decision at each POLICY_DECISION node is produced only by the
feature-t6 Policy Gate as an ALLOW policy-decision fact whose `outcome` is the topology edge label
(`Budget Remains` or `Budget Exhausted`, Assistant KB-264); progression consumes that fact. This package
holds the configuration key, the pure window and count derivation the Policy Gate reads, the decision
command that evaluates and routes in one Domain Core transaction, and the narrowing of feature-t2's
generic commands at the budget nodes. It holds no second Workflow state and no budget database: grants,
consumptions and exhaustions are reconstructed from immutable facts, commits and configuration history.

Consumed through sdd/spec.md §8 and the founding-archive fixed text (D-04 §7: Policy produces Budget
Decision Facts and never moves the Workflow); no Decision file is re-established here (feature-t5:KB-01).
"""
