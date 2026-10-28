"""Reading the stated recommendation from a review. No API access needed."""
from __future__ import annotations

import pytest

from harness.recommendations import read


@pytest.mark.parametrize("text, option, how", [
    ("... substantial.\n\n**Recommendation to the editor: Major revision**", "Major revision", "auto"),
    ("I therefore recommend a major revision.\n\n---\n\n**Recommendation to the Editor: Major revision**", "Major revision", "auto"),
    ("### Recommendation\n\n**Minor revision**", "Minor revision", "auto"),
    ("I recommend a **Minor Revision** (or a very straightforward Major Revision).\n\n**Recommendation:** Minor revision", None, "hand"),
    ("Recommendation: Accept with minor revisions.", None, "hand"),
    ("The paper is strong. I recommend that the authors report the counts.", None, "none"),
    ("The results were accepted by the field. Recommendation: Reject", "Reject", "auto"),
])
def test_read(text, option, how):
    assert read(text) == (option, how)
