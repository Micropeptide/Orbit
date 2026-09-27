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
