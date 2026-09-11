"""Make this program's own output survive the console it is printed to.

### The defect this exists for

On the first real run of the migrated system, 2026-09-11, the ``mark`` step died::

    mark failed after 0s — UnicodeEncodeError: 'charmap' codec can't encode
    character '\\u20b9' in position 268

``\\u20b9`` is ``₹``. Nothing was wrong with the figure, the book or the step: Windows' default
encoding is cp1252, which has no rupee sign, and Python falls back to it whenever stdout is a pipe
rather than a console. `uv run` pipes its child's output, so every ``print`` carrying a rupee amount
— which is most of them in a program about money — was one character away from killing its step.

The run behaved correctly around it: the failure was recorded, the evening continued, and the page
said which step died and why. That is the design working. It is still a step that did not happen
because of a currency symbol.

**Fixed at the stream, not at the call sites.** There are hundreds of prints carrying ``₹``, ``✓``
and ``§``, and a rule that every one of them must remember to be ASCII is a rule that will be broken
by the next person to add one. ``errors="replace"`` is a backstop below that: on a console that
genuinely cannot render a glyph, a ``?`` is a worse-looking line, and a crash is a missing step.
"""

from __future__ import annotations

import sys


def use_utf8() -> None:
    """Print UTF-8 whatever this process was attached to. Safe to call more than once.

    Call it first thing in an entry point. It is deliberately not done at import time: a module that
    reconfigures a shared stream merely by being imported would reach into pytest's capture and into
    any program that embeds this one.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue  # already wrapped by a test harness or a caller; leave it alone
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # A detached or already-closed stream. Nothing to fix and nothing worth raising over:
            # this function exists to stop output from killing a run, not to become the thing that
            # kills one.
            continue
