"""Write a file so that a failure leaves the old one, not half of the new one.

### The defect this exists for

On the first real run of the migrated system, 2026-09-11, the ``mark`` step died on a rupee sign
(see :mod:`qalpha.live.console`). It died **inside**::

    DASHBOARD_MD.write_text(render_markdown(...))

``Path.write_text`` opens the file, which truncates it, and *then* encodes. So the encoding error
arrived after the old report had already been thrown away, and `reports/paper_dashboard.md` was left
**zero bytes long**. The step that failed did not leave yesterday's report standing. It left nothing.

That is the same lesson twice in this repo. ``save_parquet`` was made atomic on 2026-09-07 — the one
recorded exception to rule (a) — because a killed job left a half-written panel that later reads
treated as data. The markdown and JSON writers never got the same treatment, and one of them holds
the paper book.

**Temp file beside the target, then ``os.replace``.** That call is atomic on POSIX and on Windows:
a reader sees the whole old file or the whole new one, never a partial write and never an empty one.
The temp file lives in the same directory because ``os.replace`` across filesystems is not atomic.

**UTF-8, always.** ``write_text`` without an explicit encoding uses the platform's, which is cp1252
on this machine, which has no ``₹``. A program about rupees may not depend on that.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_text(path: Path | str, text: str) -> Path:
    """Replace ``path`` with ``text``, atomically and in UTF-8. Returns the path written.

    Creates the parent directory if it is missing, because every caller was doing that itself and
    one of them will forget.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(out.parent), suffix=".tmp", prefix=out.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, out)
    except BaseException:
        # Including KeyboardInterrupt: a Ctrl-C mid-write must not leave a .tmp behind either, and
        # it must certainly not leave the target destroyed.
        Path(tmp).unlink(missing_ok=True)
        raise
    return out


def write_bytes(path: Path | str, payload: bytes) -> Path:
    """Replace ``path`` with ``payload``, atomically. Returns the path written.

    The byte-shaped twin of :func:`write_text`, and it exists for the same reason: a gzip or a
    parquet truncated halfway is not a smaller file, it is an unreadable one, and a later run that
    finds it has no way to tell it apart from a corrupt download.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(out.parent), suffix=".tmp", prefix=out.name + ".")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, out)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return out
