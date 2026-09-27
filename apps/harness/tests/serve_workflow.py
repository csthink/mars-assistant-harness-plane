"""Explicit test composition root: real serve-stdio over the production Domain Core.

This is the same HarnessDomain the product entrypoint installs; the only difference is that the
repository is a synthetic product line carrying the .synthetic-hp-domain marker, which the product
entrypoint neither requires nor checks.
"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from domain.core import HarnessDomain
from runtime.main import run

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["serve-stdio"])
    parser.add_argument("--launch-config", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    args = parser.parse_args()
    if not (args.repository / ".synthetic-hp-domain").is_file():
        raise SystemExit("Synthetic repository marker required")
    run(HarnessDomain(args.repository, entry="runtime"), json.loads(args.launch_config.read_text()))

if __name__ == "__main__":
    main()
