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


class atomic_writer:
    """Streaming atomic writes: use as a context manager for
    outputs too large to build in memory (survivors.jsonl with
    thousands of records). Writes go to a tmp file in the same
    directory; on a clean exit the tmp file is fsynced and moved
    into place with os.replace. On ANY exception (including a
    kill — the tmp file is simply left behind) the target is
    untouched: the old target stays intact, or no target exists
    at all. A leftover .tmp-* file is harmless litter.

        with atomic_writer(path) as fh:
            fh.write(...)
    """
    def __init__(self, path, encoding="utf-8"):
        self._path = Path(path)
        self._encoding = encoding
        self._tmp = None
        self._fh = None

    def __enter__(self):
        self._tmp = _tmp_path(self._path)
        self._fh = open(self._tmp, "w", encoding=self._encoding)
        return self._fh

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self._fh.flush()
                os.fsync(self._fh.fileno())
            self._fh.close()
        finally:
            self._fh = None
        if exc_type is None:
            os.replace(self._tmp, self._path)
        else:
            try:
                self._tmp.unlink()
            except OSError:
                pass
        return False
