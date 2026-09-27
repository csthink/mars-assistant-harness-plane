"""feature-t0 task acceptance domain: source resolution, idempotent acceptance, claims and bounded concurrency.

Consumers: standalone CLI (cli/main.py) and the Runtime action binding (runtime_binding.py).
Both call accept.accept_task; neither keeps a second rule set or task state.
"""
