"""Locate fixed files of a product-line instance area for the few tests and report generators that read one.

This repository carries the mechanism area only (apps/, mechanisms/, .agents/). The instance area of a product
line (sdd/, tasks/, records/, ...) stays with that product line; a handful of tests and report generators compare
against fixed files recorded there and find them through two environment variables:

  HARNESS_INSTANCE_ROOT     directory that holds the instance area's top-level entries (sdd/, tasks/, ...).
  HARNESS_INSTANCE_RECORDS  directory that holds the instance area's records/ tree. Unset means
                            $HARNESS_INSTANCE_ROOT/records, which is the layout inside a product-line repository.

Paths are written as inside the instance area ("sdd/milestones.md", "records/diagnostics/..."): a path whose first
segment is records/ resolves under the records directory, any other path under the root. When HARNESS_INSTANCE_ROOT
is unset, tests that need an instance file skip with REASON and report generators refuse to start; every other test
runs unchanged. The files are only read, never written.
"""
import os
from pathlib import Path
import unittest

ROOT_VARIABLE = "HARNESS_INSTANCE_ROOT"
RECORDS_VARIABLE = "HARNESS_INSTANCE_RECORDS"
REASON = (ROOT_VARIABLE + " is not set: this case reads fixed files of a product-line instance area, "
          "which this repository does not carry")


def configured():
    return bool(os.environ.get(ROOT_VARIABLE))


def path(relative):
    """The location of an instance-area path such as "sdd/milestones.md" or "records/governance/...". """
    root = os.environ.get(ROOT_VARIABLE)
    if not root:
        raise LookupError(REASON)
    head, _, rest = relative.partition("/")
    if head == "records":
        return Path(os.environ.get(RECORDS_VARIABLE) or os.path.join(root, "records")) / rest
    return Path(root) / relative


def locate(relative, repository):
    """A path of the product-line layout: mechanism-area paths (apps/, mechanisms/, .agents/) under this repository,
    instance-area paths through path()."""
    return Path(repository) / relative if relative.startswith(("apps/", "mechanisms/", ".agents/")) else path(relative)


def require():
    """For report generators: stop with REASON when the instance area is not configured."""
    if not configured():
        raise SystemExit(REASON)


needed = unittest.skipUnless(configured(), REASON)
