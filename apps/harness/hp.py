"""Development product command; distribution bundle belongs to feature-t18.

serve-stdio      -> runtime.main (feature-t16 Runtime Contract adapter)
task / config    -> cli.main (feature-t0 task acceptance, same domain function as the Runtime action)
workflow         -> cli.main (feature-t2 Workflow progression, same domain function as the Runtime action)
definition       -> cli.main (feature-t3 Define Task and Review Definition, same domain function as the Runtime action)
policy           -> cli.main (feature-t6 Policy Gate, same Domain Core command as the execution-port callback)
implement/verify -> cli.main (feature-t4 Implement and Verify loop, same Domain Core command point)
budget/validate  -> cli.main (feature-t5 autonomous budget and Validate Change loop, same Domain Core command point)
publish          -> cli.main (feature-t7 Publish and controlled recovery, same Domain Core command point)
binding          -> runtime.launch (feature-t18 instance binding file of the Runtime development bundle)

Before any route runs, the repository-locating Git variables are removed from this process
(runtime.launch.ignore_git_environment, feature-t18:KB-03): every route addresses only the repository it names.
"""
import sys

def main(argv=None):
    from runtime.launch import ignore_git_environment
    ignore_git_environment()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("task", "config", "workflow", "definition", "policy", "implement", "verify", "budget", "validate", "publish"):
        from cli.main import main as cli_main
        return cli_main(argv)
    if argv and argv[0] == "binding":
        from runtime.launch import binding_main
        return binding_main(argv[1:])
    from runtime.main import main as runtime_main
    sys.argv = [sys.argv[0], *argv]
    return runtime_main()

if __name__ == "__main__":
    raise SystemExit(main())
