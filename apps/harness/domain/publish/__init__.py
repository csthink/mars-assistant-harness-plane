"""feature-t7: Publish and controlled recovery of MVP_Workflow_v5 (spec FR-29, FR-30, FR-32, FR-42, FR-63, C-07).

Both paths into Publish carry one Human's explicit authorization that binds the exact pushed commit, the
source branch, the remote and its push address, the target branch, the platform repository and the pull
request title and body, together with the digest of the Publish authorization context the Human saw:
`Publish authorization` at the Publish Authorization Gate through this package, and Validation escalation
`Accept With reservation` through feature-t5's entry, which carries the same binding in the same decision
(FR-26). At the Publish node the push permit comes from feature-t6's Policy Gate; only an ALLOW releases the
external work. The pushed task-branch ref and the created or identified GitHub pull request are read back
before the lifecycle finalisation is committed. Not happened, partial, uncontrolled and unknown outcomes keep
separate evidence; an unknown outcome is resolved only by querying the same publish operation, and any
remedy that changes the remote or the platform needs a single Human recovery authorization (D-05).

Nothing here merges, closes or edits a pull request, deletes a branch or updates the target branch. This
package keeps no second Workflow state: its ledger lives in the task record of the one domain state.

Consumed through sdd/spec.md §8 and the founding-archive fixed text (D-03 §5, D-04 §7 to §13, D-05 §2 to
§10); no Decision file is re-established here (feature-t7:KB-01).
"""
