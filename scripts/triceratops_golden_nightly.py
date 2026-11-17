#!/usr/bin/env python3
"""TRICERATOPS golden-test nightly driver (Phase 3, P3-8).

Runs the golden targets (the committed fixtures in
tests/fixtures/triceratops/) through the REAL TRICERATOPS
tool on the Mac, checks each fresh output against its
fixture's TB-4 bands (via gauntlet/triceratops_golden.py —
the same definition of "passes" the CI assertions use),
writes a timestamped receipt, and opens a GitHub issue on
failure (mirroring live.yml's dedupe).

This is MONITORING, not a merge check (TB-3/TB-12): the
offline fixture assertions in CI are the merge gate. The
nightly catches tool/environment drift (a TRILEGAL change,
a venv break, a Gaia outage) that CI cannot see. Phase 3
completion is gated on a green receipt < 7 days old
(--check mode implements the gate).

Inputs: the C-10 tool inputs, re-run as-is (a golden test
re-runs the SAME inputs and expects the SAME outputs within
bands). --inputs-dir holds one subdirectory per golden
target with an input.json inside:
    <inputs-dir>/<tic>/input.json
On the Mac the C-10 inputs live under
vetting_results/triceratops-verify/ (see the extraction
notes in hidden_files/science-vet/phase3-vote/
p3-9-panel-mac-commands.md for the exact layout).

Modes:
  full (default): N=1,000,000 draws per target; the receipt
      is gate-eligible (fast=false).
  --fast: N=10,000 draws (P-16, for iteration). The fast
      run checks PLUMBING only (each run completes with a
      schema-valid output) — a 10k-draw FPP is too noisy
      for the bands. A fast receipt is never gate-eligible.

Memory: every run goes through run_external_tool with the
RSS watchdog at the policy's memory_mb (P-3, scoped to this
job — macOS applies no RLIMIT_AS cap). The receipt records
peak RSS per run (the P3-8 memory measurement).

SSL: the driver sets SSL_CERT_FILE to the TRICERATOPS
venv's certifi bundle (the TRILEGAL host omits a ZeroSSL
intermediate; the intermediate was appended to the venv
bundle — re-add after any certifi upgrade).

Scheduling: a Mac cron/launchd job, nightly, wrapped in
caffeinate -s -i (clamshell sleep fires on AC). The job
must be LOUD on failure: non-zero exit + a GitHub issue
(or a FAILURE marker + loud stderr when `gh` is
unavailable). Silent cron failures are a known Mac risk.

Receipt: --receipt (default
vetting_results/triceratops-golden/receipt.json — run data,
not a calibration profile, so it lives outside
calibration/). The receipt carries a receipt_hash (sha256
over the canonical receipt body) — tamper-evident, not a
cryptographic signature: the project has no signing-key
infrastructure, and the hash chain (fixture shas + code SHA
+ policy sha + results) is what makes the receipt
verifiable from a copy. The receipt records the effective
per-target timeout (timeout_s, PM-2) — the policy default
unless --timeout-s overrode it.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import load_profile, profile_sha256  # noqa: E402
from gauntlet import triceratops_golden as _golden  # noqa: E402
from gauntlet.external_tool import (  # noqa: E402
    load_external_tool_configs, run_external_tool)
from validation import validate_triceratops_output  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUTS_DIR = REPO_ROOT / "vetting_results" / "triceratops-verify"
DEFAULT_RECEIPT = (REPO_ROOT / "vetting_results"
                   / "triceratops-golden" / "receipt.json")
DEFAULT_WORKDIR = (REPO_ROOT / "vetting_results"
                   / "triceratops-golden" / "work")
FAST_N_SAMPLES = 10_000
RECEIPT_MAX_AGE_DAYS = 7
ISSUE_SEARCH = "triceratops-golden failure in:title"


def _git_info():
    """(sha, dirty) best-effort — 'unknown'/None when git
    is unavailable (the receipt records the gap)."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
            capture_output=True, text=True,
            timeout=30).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=REPO_ROOT,
            capture_output=True, text=True,
            timeout=30).stdout.strip()
        return sha or "unknown", bool(dirty)
    except (OSError, subprocess.SubprocessError):
        return "unknown", None


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _set_ssl_cert_file(venv_python):
    """Point SSL_CERT_FILE at the tool venv's certifi bundle
    (the TRILEGAL host omits a ZeroSSL intermediate). Only
    when unset, only when the venv can name its bundle.
    Returns the path set, or None."""
    if os.environ.get("SSL_CERT_FILE"):
        return os.environ["SSL_CERT_FILE"]
    try:
        out = subprocess.run(
            [venv_python, "-c",
             "import certifi; print(certifi.where())"],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    path = out.stdout.strip()
    if out.returncode == 0 and path and os.path.exists(path):
        os.environ["SSL_CERT_FILE"] = path
        return path
    return None


def _receipt_hash(body):
    """sha256 over the canonical JSON of the receipt body
    (without the hash field itself)."""
    canonical = json.dumps(body, sort_keys=True,
                           separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _open_failure_issue(summary, receipt_path, sha):
    """Open a GitHub issue on failure, deduplicated by title
    (live.yml's pattern). Returns (opened, note): opened is
    True when an issue was created, False when one is already
    open or `gh` is unavailable — the note says which, so the
    caller can be loud about it either way."""
    try:
        listed = subprocess.run(
            ["gh", "issue", "list", "--state", "open",
             "--search", ISSUE_SEARCH, "--json", "number",
             "--jq", "length"],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"gh unavailable ({exc}) — no issue opened"
    if listed.returncode != 0:
        return False, ("gh issue list failed: "
                       f"{listed.stderr.strip()[:200]}")
    if listed.stdout.strip() not in ("", "0"):
        return False, ("an open triceratops-golden failure "
                       "issue already exists — not opening "
                       "another")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    body = (
        "The TRICERATOPS golden-test nightly failed.\n\n"
        f"Summary: {summary}\n\n"
        f"Receipt: {receipt_path}\n"
        f"Commit: {sha}\n\n"
        "Diagnosis (see scripts/triceratops_golden_nightly.py):\n"
        "- If the CI golden assertions are GREEN, the tool or "
        "its environment drifted (TRILEGAL/neighbour data, a "
        "venv break, a Gaia outage) — check the receipt's "
        "per-target failures and the Mac venv.\n"
        "- If CI is red too, the pipeline or the policy "
        "changed — find what broke before merging anything.\n")
    try:
        created = subprocess.run(
            ["gh", "issue", "create",
             "--title", ("triceratops-golden failure: "
                         f"golden run failed on {today}"),
             "--body", body],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"gh issue create failed ({exc})"
    if created.returncode != 0:
        return False, ("gh issue create failed: "
                       f"{created.stderr.strip()[:200]}")
    return True, created.stdout.strip()


def run_nightly(inputs_dir, fixtures_dir, receipt_path, workdir,
                policy_name="external_tools_v2", fast=False,
                no_issue=False, timeout_s=None, memory_mb=None,
                config_override=None, rss_poll_s=5.0):
    """Run the golden targets; write the receipt; open an
    issue on failure unless no_issue. Returns (passed, receipt
    dict). Never raises for a tool-side failure — every
    failure mode lands in the receipt.

    config_override: a ToolConfig replacing the policy's
    triceratops config (a TEST seam — the offline tests run a
    fake wrapper). A receipt produced with an override is
    marked and is never gate-eligible (see check_receipt)."""
    _golden.FIXTURE_DIR = Path(fixtures_dir)
    policy = load_profile(policy_name)
    if config_override is not None:
        config = config_override
    else:
        configs = load_external_tool_configs(policy_name)
        config = configs["triceratops"]
    if timeout_s is not None:
        config = config.__class__(**{**config.__dict__,
                                     "timeout_s": timeout_s})
    cap_mb = memory_mb if memory_mb is not None else config.memory_mb
    ssl_path = _set_ssl_cert_file(config.python)
    sha, dirty = _git_info()
    stamp = datetime.now(timezone.utc).isoformat()
    results = {}
    overall_pass = True
    for tic in _golden.fixture_tics():
        fixture = _golden.load_fixture(tic)
        entry = {"fixture_sha256": _sha256_file(
            Path(fixtures_dir) / f"{tic}.json")}
        input_path = Path(inputs_dir) / tic / "input.json"
        if not input_path.exists():
            entry.update(status="missing_input",
                         failures=[f"no input at {input_path}"])
            overall_pass = False
            results[tic] = entry
            continue
        with open(input_path) as fh:
            tool_input = json.load(fh)
        if fast:
            tool_input["n_samples"] = FAST_N_SAMPLES
        res = run_external_tool(
            config, tool_input,
            str(Path(workdir) / tic),
            rss_watchdog_mb=cap_mb, rss_poll_s=rss_poll_s)
        entry.update(run_status=res.status,
                     wall_time_s=round(res.wall_time_s, 1),
                     peak_rss_mb=(round(res.peak_rss_mb, 1)
                                  if res.peak_rss_mb is not None
                                  else None),
                     rss_watchdog_applied=res.rss_watchdog_applied)
        if res.status != "completed":
            entry.update(status="run_failed",
                         failures=[f"{res.status}: "
                                   f"{res.stderr_tail[:500]}"])
            overall_pass = False
            results[tic] = entry
            continue
        try:
            validate_triceratops_output(res.output)
        except Exception as exc:  # noqa: BLE001 - schema failure
            entry.update(status="run_failed",
                         failures=[f"output failed schema "
                                   f"validation: {exc}"])
            overall_pass = False
            results[tic] = entry
            continue
        metrics = res.output["metrics"]
        entry.update(fpp=metrics["fpp"], nfpp=metrics["nfpp"],
                     n_samples=metrics["n_samples"])
        if fast:
            # Plumbing only: a 10k-draw FPP is too noisy for
            # the bands. The run completing + validating IS
            # the fast check.
            entry.update(status="fast_ok", failures=[])
            results[tic] = entry
            continue
        scenario = {}
        for artifact in res.output.get("artifacts") or []:
            if artifact.endswith(".csv"):
                scenario = _golden.scenario_from_probs_csv(
                    artifact)
                if scenario:
                    break
        entry["scenario"] = scenario or None
        failures = _golden.check_fixture_output(
            fixture, res.output, policy,
            scenario=scenario or None)
        entry.update(status=("pass" if not failures else "fail"),
                     failures=failures)
        if failures:
            overall_pass = False
        results[tic] = entry
    body = {
        "receipt_version": 1,
        "timestamp_utc": stamp,
        "git_sha": sha,
        "working_tree_dirty": dirty,
        "policy": policy_name,
        "policy_sha256": profile_sha256(policy_name),
        "fast": fast,
        "timeout_s": config.timeout_s,
        "ssl_cert_file": ssl_path,
        "config_override": config_override is not None,
        "overall": "pass" if overall_pass else "fail",
        "targets": results,
        "issue": None,
    }
    if not overall_pass and not no_issue:
        failed = [t for t, r in results.items()
                  if r["status"] not in ("pass", "fast_ok")]
        opened, note = _open_failure_issue(
            f"{len(failed)} target(s) failed: "
            f"{', '.join(failed)}", str(receipt_path), sha)
        body["issue"] = {"opened": opened, "note": note}
        if not opened:
            print(f"WARNING: failure issue NOT opened: {note}",
                  file=sys.stderr)
            (Path(receipt_path).parent / "FAILURE").write_text(
                f"{stamp}: golden run failed; issue not opened: "
                f"{note}\n")
    # The hash covers the whole body INCLUDING the issue info
    # (added above, before hashing) — otherwise the gate
    # check would fail on every red receipt.
    receipt = dict(body, receipt_hash=_receipt_hash(body))
    receipt_path = Path(receipt_path)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    with open(receipt_path, "w") as fh:
        json.dump(receipt, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return overall_pass, receipt


def check_receipt(receipt_path, max_age_days=RECEIPT_MAX_AGE_DAYS):
    """The receipt gate: (green, reason). Green requires the
    file to exist + parse + the hash to verify + overall pass
    + a full (not fast) run + no config override + a
    timestamp within max_age_days.
    """
    try:
        with open(receipt_path) as fh:
            receipt = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"receipt unreadable: {exc}"
    claimed = receipt.pop("receipt_hash", None)
    if claimed is None:
        return False, "receipt has no receipt_hash"
    if _receipt_hash(receipt) != claimed:
        return False, "receipt_hash mismatch (tampered?)"
    if receipt.get("overall") != "pass":
        return False, (f"overall is {receipt.get('overall')!r}, "
                       f"not 'pass'")
    if receipt.get("fast"):
        return False, "fast (smoke) receipts are not gate-eligible"
    if receipt.get("config_override"):
        return False, ("receipt used a config override (test "
                       "seam) — not gate-eligible")
    try:
        stamp = datetime.fromisoformat(
            receipt["timestamp_utc"])
    except (KeyError, ValueError) as exc:
        return False, f"bad timestamp: {exc}"
    age_days = (datetime.now(timezone.utc) - stamp).total_seconds() / 86400
    if age_days > max_age_days:
        return False, (f"receipt is {age_days:.1f} days old "
                       f"(max {max_age_days})")
    return True, (f"green: overall pass, {age_days:.1f} days old, "
                  f"targets {sorted(receipt.get('targets', {}))}")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="TRICERATOPS golden-test nightly (P3-8).")
    ap.add_argument("--check", metavar="RECEIPT",
                    help="gate-check a receipt and exit 0/1")
    ap.add_argument("--max-age-days", type=float,
                    default=RECEIPT_MAX_AGE_DAYS,
                    help="receipt max age for --check (days)")
    ap.add_argument("--inputs-dir", default=str(DEFAULT_INPUTS_DIR),
                    help="dir with <tic>/input.json per target")
    ap.add_argument("--fixtures-dir",
                    default=str(_golden.FIXTURE_DIR),
                    help="golden fixture dir")
    ap.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    ap.add_argument("--workdir", default=str(DEFAULT_WORKDIR))
    ap.add_argument("--policy", default="external_tools_v2")
    ap.add_argument("--fast", action="store_true",
                    help="N=10,000 smoke run (plumbing only; "
                    "never gate-eligible)")
    ap.add_argument("--no-issue", action="store_true",
                    help="do not open a GitHub issue on failure")
    ap.add_argument("--timeout-s", type=int, default=None)
    ap.add_argument("--memory-mb", type=int, default=None)
    args = ap.parse_args(argv)
    if args.check:
        green, reason = check_receipt(args.check,
                                      args.max_age_days)
        print(reason)
        return 0 if green else 1
    passed, receipt = run_nightly(
        args.inputs_dir, args.fixtures_dir, args.receipt,
        args.workdir, policy_name=args.policy, fast=args.fast,
        no_issue=args.no_issue, timeout_s=args.timeout_s,
        memory_mb=args.memory_mb)
    print(f"golden nightly: overall {receipt['overall']} "
          f"({'fast' if args.fast else 'full'}); "
          f"receipt {args.receipt}")
    for tic, entry in receipt["targets"].items():
        print(f"  TIC {tic}: {entry['status']} "
              f"(fpp={entry.get('fpp')}, "
              f"wall={entry.get('wall_time_s')} s, "
              f"peak_rss={entry.get('peak_rss_mb')} MB)")
        for failure in entry.get("failures") or []:
            print(f"    FAIL: {failure}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
