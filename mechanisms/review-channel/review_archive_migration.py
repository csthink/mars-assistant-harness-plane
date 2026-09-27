#!/usr/bin/env python3
"""Explicit additive archive installation/import; no switch or source deletion.

Owner authorization is provided by the calling workflow. This command checks
source bytes, dual publication and an isolated restore; it cannot approve them.
The migration plan and verification originals must be kept outside product Git.
"""

import argparse
import json
import sys
import review_evidence as E


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo-root", required=True)
    p.add_argument("--repository-id", required=True)
    p.add_argument("--primary-root", required=True)
    p.add_argument("--backup-root", required=True)
    p.add_argument("--plan", required=True)
    p.add_argument("--restore-root", required=True)
    args = p.parse_args(argv)
    try:
        plan = E.strict(E.read_file(args.plan))
        archive = E.initialize(
            args.repo_root, args.repository_id, args.primary_root, args.backup_root
        )
        result = E.import_migration_plan(
            args.repo_root, archive, plan, args.restore_root
        )
        print(json.dumps({"state": "COMPLETE", **result}, ensure_ascii=False, indent=2))
        return 0
    except E.EvidenceError as exc:
        print(
            json.dumps(
                {"state": "REJECTED", "failure_code": exc.code, "message": exc.message},
                ensure_ascii=False,
            )
        )
        return 1
    except OSError as exc:
        print("migration runtime failure: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
