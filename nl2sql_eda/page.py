# -*- coding: utf-8 -*-
"""Where this package's built page lives.

STDLIB ONLY, and deliberately NOT imported by ``__init__.py``.

What that buys, stated precisely: loading this entry point imports the
parent package first (Python always imports parents), so it inherits
whatever ``__init__`` needs — an engine, in our case. What it CANNOT do is
add a failure of its own. If the module loads on a given core, its page
loads too; if the module does not, the page was never going to matter.

So: no engine import here, no matplotlib, nothing that might be absent or
differently named on a core we do not control. A path built from ``__file__``
is the whole job.

A core that knows nothing about pages simply never calls this, and every
action still works. The page is a bonus, never a requirement.
"""
from pathlib import Path


def page():
    return {"path": str(Path(__file__).resolve().parent / "webdist"),
            "label": "🔬 EDA"}
