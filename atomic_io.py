"""Atomic file writes — a reader never sees a half-written file.

Every pipeline output (survivors.jsonl, summary.json, manifests,
checkpoints) is written to a temporary file in the same directory,
flushed to disk, then moved into place with ``os.replace`` — an
atomic rename on POSIX and Windows. A VM replacement, a power cut,
or a kill mid-write can leave a ``.tmp-*`` file behind, but never a
truncated target: the old target (if any) stays intact until the
new one is complete.

A leftover ``.tmp-*`` file is harmless litter, not corruption —
readers ignore it, and the next write of the same target uses a
fresh tmp name (pid + random suffix, so parallel workers never
collide).
"""
import json
import os
import secrets
from pathlib import Path


def _tmp_path(path):
    path = Path(path)
    return path.with_name(
        f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(4)}")


def atomic_write_bytes(path, data):
    """Write bytes to `path` atomically. Returns the Path."""
    path = Path(path)
    tmp = _tmp_path(path)
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return path


def atomic_write_text(path, text, encoding="utf-8"):
    """Write text to `path` atomically. Returns the Path."""
    return atomic_write_bytes(path, text.encode(encoding))


def atomic_write_json(path, obj, indent=2):
    """Write a JSON-serializable object to `path` atomically
    (json.dumps with sorted keys, so identical objects produce
    identical bytes — see the determinism test). Returns the Path."""
    text = json.dumps(obj, indent=indent, sort_keys=True) + "\n"
    return atomic_write_text(path, text)
