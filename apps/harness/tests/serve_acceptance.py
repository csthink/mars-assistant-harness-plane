"""Explicit test composition root: real serve-stdio over the acceptance domain of a synthetic product line."""
import argparse
import os
from pathlib import Path
import signal
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from domain.acceptance.runtime_binding import AcceptanceDomain
from runtime.main import run
import json

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["serve-stdio"])
    parser.add_argument("--launch-config", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--kill-at-phase", help="test-only: SIGKILL the process at an acceptance phase")
    args = parser.parse_args()
    if not (args.repository / ".synthetic-hp-domain").is_file():
        raise SystemExit("Synthetic repository marker required")
    observer = None
    if args.kill_at_phase:
        def observer(phase, detail=None):
            if phase == args.kill_at_phase:
                os.kill(os.getpid(), signal.SIGKILL)
    run(AcceptanceDomain(args.repository, observer=observer), json.loads(args.launch_config.read_text()))

if __name__ == "__main__":
    main()
