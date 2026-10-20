"""The review channel's contract module of this hp tree (mechanisms/review-channel/review_channel_contract.py).

It is the one definition of the grammar the Domain Core shares with the review channel, such as the task id
grammar (review channel design §6.1). That module holds only constants and pure functions and imports nothing
of the channel, so it is loaded here by file location under a private module name: the Domain Core always reads
this tree's copy, whatever other copy of the channel a task worktree later puts on sys.path.
"""
import importlib.util
from pathlib import Path

PATH = Path(__file__).resolve().parents[3] / "mechanisms" / "review-channel" / "review_channel_contract.py"


def _load():
    spec = importlib.util.spec_from_file_location("hp_review_channel_contract", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONTRACT = _load()
