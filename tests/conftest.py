"""What every test starts from.

The suite imports qqcore, and qqcore loads the settings this Mac is actually using. Most
of those are harmless to share, but a few reach the network: a `review_model` set in
Settings sends a borderline permission question to a real hosted model. The day one was
switched on, two tests began calling Claude Haiku from inside the suite -- and passing or
failing on its opinion. A test that needs one of these stubs it; nothing inherits it.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))

# Settings that call out to a model or a service when they are set.
_REACHES_OUT = ("review_model",)


@pytest.fixture(autouse=True)
def _nothing_calls_out_by_accident():
    import qqcore as q
    saved = {k: q.S.get(k) for k in _REACHES_OUT}
    for k in _REACHES_OUT:
        q.S[k] = ""
    yield
    for k, v in saved.items():
        q.S[k] = v


@pytest.fixture(autouse=True)
def _the_real_bin_is_never_touched(tmp_path):
    """Every test gets a bin of its own. One early test redirected only one of the bin's
    folders, and binning a test chat wrote the record -- and the file -- into the real
    one. This makes that impossible for any test, not just the ones that remember."""
    import qqcore as q
    saved = {k: getattr(q, k) for k in ("TRASH", "TRASH_SESS", "TRASH_FILE")}
    q.TRASH = str(tmp_path / "trash")
    q.TRASH_SESS = os.path.join(q.TRASH, "sessions")
    q.TRASH_FILE = os.path.join(q.TRASH, "files")
    os.makedirs(q.TRASH_SESS); os.makedirs(q.TRASH_FILE)
    yield
    for k, v in saved.items():
        setattr(q, k, v)
