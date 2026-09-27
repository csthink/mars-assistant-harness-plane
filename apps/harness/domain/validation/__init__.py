"""feature-t5: the Validate Change loop of MVP_Workflow_v5 (spec FR-24, FR-26, FR-62).

At `Validate Change · Enabled?` the switch recorded at acceptance (feature-t0) selects Enabled or Disabled;
the switch and its source are recorded as a fact. Enabled, the change review runs through the one governed
channel runner (FR-40) as an impl round, on feature-t3's purpose-agnostic execution layer and production
port wiring with feature-t6's authorization callback injected. Only a published valid impl-round verdict
enters the domain; it is bound to the reviewed candidate commit and mapped to the seven minimal semantic
classes of FR-24. Host cancel, port failure, infrastructure failure, invalid output and unknown results are
never a Reviewer FAIL and never consume budget: the attempt fails or stays indeterminate and the node
enters RECOVERY_REQUIRED. The Validation escalation Accept With reservation keeps the FAIL verdict, its
findings and the reservation as the decision context of that Publish authorization (FR-26).

Consumed through sdd/spec.md §8 and the founding-archive fixed text (D-02 §12, D-03 §5, D-04, D-05 §2);
no Decision file is re-established here (feature-t5:KB-01).
"""
