"""Test-only composition root for feature-t3 Runtime tests: real serve-stdio, production Domain Core.

Differences from the product entrypoint, all explicitly synthetic: the repository is a synthetic
product line; the feature-t6 availability check is answered by the test domain; the review executor
uses a synthetic reviewer (optionally held by a gate file) and a synthetic authorization callback.
The execution layer, its scheduling, the ruling writer and every domain command are production code.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import definition_fixture as F
from runtime.dispatcher import Dispatcher
from runtime.protocol import Schemas
from runtime.transport import Stdio


# The outcome the production runner gives when the channel refuses before allocating an attempt
# (domain.definition.dispatch.unread_outcome); HP_T3_VERDICT=REFUSED selects it.
REFUSED = dict(classification="preflight_failed", failureCode="request-unrouteable",
               problems=["task_record present but malformed"], runnerCode=1)


class GatedReviewer(F.SyntheticReviewer):
    """Waits for a gate file before answering; logs every execution start to a file (process-crossing)."""

    def __init__(self, gate, log, verdict):
        self.refused = verdict == "REFUSED"
        super().__init__(("valid", "PASS" if self.refused else verdict), mode="authority")
        self.gate_file, self.log = Path(gate) if gate else None, Path(log)

    async def __call__(self, descriptor, env, port, binding, registration, mapping):
        with self.log.open("a") as f:
            f.write(json.dumps(dict(event="execute", executionId=descriptor["executionId"], pid=os.getpid())) + "\n")
        if self.gate_file is not None:
            while not self.gate_file.exists():
                await asyncio.sleep(0.05)
        if self.refused:
            return dict(REFUSED)
        return await super().__call__(descriptor, env, port, binding, registration, mapping)

    async def query(self, descriptor, env):
        with self.log.open("a") as f:
            f.write(json.dumps(dict(event="query", executionId=descriptor["executionId"], pid=os.getpid())) + "\n")
        return dict(classification="unknown", failureCode="synthetic-query-unknown")


class DefinitionDispatcher(Dispatcher):
    def execution_executors(self):
        reviewer = GatedReviewer(os.environ.get("HP_T3_GATE"), os.environ["HP_T3_LOG"], os.environ.get("HP_T3_VERDICT", "PASS"))
        if os.environ.get("HP_T3_AUTHORIZER") == "REAL":
            return F.real_executors(reviewer)
        return F.executors(reviewer, F.synthetic_authorizer(decision=os.environ.get("HP_T3_AUTHORIZER", "ALLOW")))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["serve-stdio"])
    parser.add_argument("--launch-config", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    args = parser.parse_args()
    if not (args.repository / ".synthetic-hp-domain").is_file():
        raise SystemExit("Synthetic repository marker required")
    configuration = json.loads(args.launch_config.read_text())
    Schemas().validate("LaunchAuthorization", configuration["launchAuthorization"])
    transport = Stdio()
    transport.dispatcher = DefinitionDispatcher(F.TestHarnessDomain(args.repository, entry="runtime"), configuration, transport)
    asyncio.run(transport.run())


if __name__ == "__main__":
    main()
