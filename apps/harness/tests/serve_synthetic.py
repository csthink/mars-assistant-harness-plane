"""Explicit synthetic test composition root, never the product entrypoint."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from git_domain import GitDomain
from runtime.main import run

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["serve-stdio"])
    parser.add_argument("--launch-config", type=Path, required=True)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--fault-config", type=Path)
    args = parser.parse_args()
    run(GitDomain(args.repository, json.loads(args.seed.read_text()), args.fault_config), json.loads(args.launch_config.read_text()))

if __name__ == "__main__":
    main()
