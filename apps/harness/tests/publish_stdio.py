"""SYNTHETIC composition root and Host driver for feature-t7 through a real serve-stdio process (AC-07). Tests only.

Run as `publish_stdio.py serve-stdio --launch-config <file> --repository <synthetic product line>`: the production
Domain Core, dispatcher, Runtime actions, execution layer with the production executors (publish and
publish-query included), the feature-t6 Policy Gate and the production GitHub adapter run in the child process.
The remote is the fixture's local bare repository and the platform is the fixture's SYNTHETIC platform program,
both reached through the product-line configuration exactly as in production. PublishHost drives it with
host_driver's wire client. No real Assistant, platform, remote or model.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validation_stdio import ValidationHost

APP = Path(__file__).resolve().parents[1]


def launch_files(directory, fx):
    """launch.json / host-template.json over the fixture repository, offering the feature-t5 and feature-t7 capabilities."""
    import definition_fixture as DF
    from domain.budget import projection as budget_projection
    from domain.publish import projection as publish_projection
    from domain.validation import projection as validation_projection
    DF.runtime_files(directory, dict(repo=fx.repo, taskId=fx.task_id))
    path = Path(directory) / "host-template.json"
    template = json.loads(path.read_text())
    extra = [budget_projection.capability(), validation_projection.capability(), publish_projection.capability()]
    for holder in (template, template["initialize"]):
        holder["capabilities"] = holder["capabilities"] + extra
    path.write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n")
    return template


class PublishHost(ValidationHost):
    def __init__(self, directory, env, output=None):
        directory = Path(directory)
        template = json.loads((directory / "host-template.json").read_text())
        command = [sys.executable, str(APP / "tests/publish_stdio.py"), "serve-stdio",
                   "--launch-config", str(directory / "launch.json"), "--repository", template["repository"]]
        saved = dict(os.environ)
        os.environ.update(env)
        try:
            super(ValidationHost, self).__init__(directory, output=output, command=command)
        finally:
            os.environ.clear()
            os.environ.update(saved)


def serve():
    from domain.core import HarnessDomain
    from runtime.dispatcher import Dispatcher
    from runtime.protocol import Schemas
    from runtime.transport import Stdio

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
    transport.dispatcher = Dispatcher(HarnessDomain(args.repository, entry="runtime"), configuration, transport)
    asyncio.run(transport.run())


if __name__ == "__main__":
    serve()
