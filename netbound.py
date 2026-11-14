"""Bounded network access (Phase 1.2, item C-1).

Every network call in this repo must be bounded: "MAST hung" is a
code issue — the wait was unbounded. This module is the one place
timeouts live:

* ``http_get`` — requests with a (connect, read) timeout tuple +
  bounded retries with backoff. Use it for plain HTTP calls.
* ``run_with_timeout`` — a daemon-thread watchdog for calls that
  take no timeout of their own: astroquery's Catalogs queries and
  lightkurve's search/download take no timeout parameter (this
  astroquery version exposes no TIMEOUT attribute to set, verified
  2026-11-14), so the only way to bound them is to watch them
  from another thread.
* ``mast_call`` — ``run_with_timeout`` with the MAST default.
* ``download_file`` — streaming download to a file with a
  timeout; replaces ``urllib.request.urlretrieve``, which takes
  no timeout at all.

What the watchdog guarantees — and what it does not. It bounds
the CALLER's wait: after ``timeout_s`` the caller gets a
``NetworkTimeout`` and moves on. It cannot kill the underlying
call — a Python thread cannot be killed — so a hung socket keeps
one daemon thread until the OS or the server closes it. The
thread is a daemon, so it never blocks interpreter exit, and a
hung network call is finite in practice (TCP/proxy timeouts close
it). What matters for the pipeline is that no run waits forever
and every timeout is recorded as ``unmeasured`` with a reason —
never a hang, never a silent pass. In the bulk screen that is the
``"unmeasured"`` screen status (``run_chunked.SCREEN_STATUSES``);
in the gauntlet the runner already maps a stage exception to
unmeasured + EXEC_ERROR, so a NetworkTimeout raised inside a
stage adapter lands there.
"""
import threading
import time
import urllib.request

import requests

# Per-call connect/read timeouts for plain HTTP (requests).
CONNECT_TIMEOUT_S = 10.0
READ_TIMEOUT_S = 120.0
# Watchdog bound for one astroquery/lightkurve call (search or
# download): MAST answers catalog queries in seconds and a FITS
# download in well under a minute on a healthy connection; 300 s
# is a hang, not a slow call.
MAST_CALL_TIMEOUT_S = 300.0
# Per-star watchdog for the bulk screen loop (download + BLS on
# one star): a star screens in seconds; 600 s is a pathological
# star, not a slow one.
STAR_TIMEOUT_S = 600.0


class NetworkTimeout(TimeoutError):
    """A bounded network call (or a watched one) ran out of time.

    A TimeoutError subclass, so hunter's connection-error
    classifier treats it as a transient, retryable failure —
    a timeout is a dropped connection by another name.
    """


def run_with_timeout(fn, timeout_s, name="network call"):
    """Run ``fn()`` and return its value, or raise NetworkTimeout
    if it has not returned within ``timeout_s`` seconds.

    Implemented with a daemon thread + join: no executor, so a
    timed-out call never blocks shutdown (ThreadPoolExecutor's
    context manager would wait for the hung thread). The worker
    thread keeps running after the timeout — it cannot be killed
    — but it is a daemon and dies with the process. Exceptions
    raised by ``fn`` propagate unchanged.
    """
    result = {}

    def _target():
        try:
            result["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            result["error"] = exc

    t = threading.Thread(target=_target, daemon=True,
                         name=f"netbound:{name}")
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        raise NetworkTimeout(
            f"{name} timed out after {timeout_s:g}s")
    if "error" in result:
        raise result["error"]
    return result.get("value")


def mast_call(fn, timeout_s=MAST_CALL_TIMEOUT_S, name="MAST call"):
    """``run_with_timeout`` with the MAST default — the wrapper
    for astroquery/lightkurve calls, which take no timeout of
    their own."""
    return run_with_timeout(fn, timeout_s, name)


def http_get(url, timeout=(CONNECT_TIMEOUT_S, READ_TIMEOUT_S),
             retries=3, backoff=(5.0, 15.0), **kwargs):
    """requests.get with a (connect, read) timeout tuple and
    bounded retries on connection-class failures.

    ``retries`` is the total attempt count (initial + retries);
    ``backoff`` is the wait in seconds between attempts (its last
    value repeats). A timeout on the final attempt raises
    NetworkTimeout; other final failures re-raise unchanged.
    Extra ``kwargs`` pass through to requests.get (headers,
    params, ...).
    """
    last = None
    for attempt in range(1, retries + 1):
        try:
            return requests.get(url, timeout=timeout, **kwargs)
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as exc:
            last = exc
            if attempt >= retries:
                break
            wait = backoff[min(attempt - 1, len(backoff) - 1)]
            time.sleep(wait)
    if isinstance(last, requests.exceptions.Timeout):
        raise NetworkTimeout(
            f"GET {url} timed out after {retries} attempt(s)")
    raise last


def download_file(url, dest, timeout_s=READ_TIMEOUT_S,
                  chunk_size=1 << 20):
    """Stream ``url`` to ``dest`` with a read timeout.

    Replaces ``urllib.request.urlretrieve`` (no timeout
    parameter). Writes to a ``.part`` sibling and renames on
    success, so an interrupted download never leaves a truncated
    file at the destination. Returns the bytes written.
    """
    from pathlib import Path
    dest = Path(dest)
    tmp = dest.with_suffix(".part")
    written = 0
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:
        with open(tmp, "wb") as fh:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                fh.write(chunk)
                written += len(chunk)
    tmp.rename(dest)
    return written
