"""Test-only: run one acceptance in a subprocess and SIGKILL at a named phase (AC-05 breakpoints)."""
import json
import os
from pathlib import Path
import signal
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from domain.acceptance.accept import accept_task
from domain.acceptance.results import Rejection
from domain.acceptance.schema import DIGEST, SCHEMA_ID
from domain.store import RuntimeStore

def main():
    phase, request = sys.argv[1], json.loads(Path(sys.argv[2]).read_text())
    marker = Path(request["repository"]) / ".synthetic-hp-domain"
    if not marker.is_file():
        raise SystemExit("Synthetic repository marker required")
    def observer(current, detail=None):
        if current == phase:
            Path(sys.argv[2]).with_suffix(".fired.json").write_text(json.dumps(dict(phase=current, pid=os.getpid())))
            os.kill(os.getpid(), signal.SIGKILL)
    store = RuntimeStore(request["repository"], payload_schemas={DIGEST: SCHEMA_ID})
    try:
        print(json.dumps(accept_task(store, request, observer=observer)))
    except Rejection as exc:
        print(json.dumps(dict(result=exc.code, reason=exc.reason())))
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
