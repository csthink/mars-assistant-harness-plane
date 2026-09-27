"""feature-t6: the Policy Gate minimal closed set.

The Policy Gate is the only producer of Policy Decision facts. It evaluates a fixed closed set of
judgement items fail-closed and records one immutable `policy-decision` fact through the feature-t2
Domain Core; it never moves the Workflow, starts or releases an execution, or performs a remote
action. The logical contracts consumed here come through sdd/spec.md §8 (D-03 -> FR-22, D-04 ->
FR-31 / NFR-01, D-05 -> FR-30) and the founding-archive fixed original text; none of D-03, D-04 or
D-05 is re-established as an hp Decision file (feature-t6:KB-01) and nothing here substitutes for one.

Execution boundaries are reported exactly as the execution profile declares them. Nothing in this
package claims operating-system isolation or mechanical blocking of arbitrary Agent operations.
"""
