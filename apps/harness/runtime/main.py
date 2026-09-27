"""Product entrypoint. No test adapter imports or synthetic fallback.

serve-stdio binds the production Domain Core (feature-t2) to exactly one product-line repository and
hands it to the Runtime as the DomainPort, in place of the UnavailableDomain feature-t16 shipped
with. The repository comes from the launcher, either as --repository or as the repository field of
the launch configuration, never from a wire request. Without a usable repository the Runtime still
starts and reports health degraded with the reason, rather than claiming a domain is installed.

serve-stdio --bundle is the launch mode of the Runtime development bundle (feature-t18, runtime/launch.py):
identities come from Initialize, the repository from the instance binding file.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys

from domain.core import DegradedDomain, open_domain
from runtime.dispatcher import Dispatcher
from runtime.protocol import Schemas
from runtime.transport import Stdio

NO_REPOSITORY = ("No product-line repository was given to serve-stdio; pass --repository or set the "
                 "repository field in the launch configuration")

def run(domain, configuration):
    schemas = Schemas()
    schemas.validate("LaunchAuthorization", configuration["launchAuthorization"])
    transport = Stdio()
    transport.dispatcher = Dispatcher(domain, configuration, transport)
    asyncio.run(transport.run())

def domain_for(repository):
    return open_domain(repository, entry="runtime") if repository else DegradedDomain(NO_REPOSITORY)

def main():
    if "--bundle" in sys.argv[1:]:
        from runtime.launch import main as bundle_main
        return bundle_main(sys.argv[1:])
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["serve-stdio"])
    parser.add_argument("--launch-config", required=True, type=Path)
    parser.add_argument("--repository", type=Path, default=None)
    args = parser.parse_args()
    config = json.loads(args.launch_config.read_text())
    run(domain_for(args.repository or config.get("repository")), config)

if __name__ == "__main__":
    main()
