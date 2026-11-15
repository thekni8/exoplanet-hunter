"""Drive LATTE (Eisner et al. 2020) for one target (Phase 2, 2B).

Runs INSIDE the LATTE venv on the Mac, invoked by
gauntlet/external_tool.py as:

    python run_latte.py --input <input.json> --output <output.json>

Reads the C-10 input JSON, writes a LATTE --targetlist CSV
(TICID, period, t0, sectors, BLS, model, FFI), runs
`python -m LATTE --targetlist=<csv> --o --noshow` as a nested
subprocess, and writes the C-10 output JSON (schema
latte-output-schema.json).

LATTE specifics, verified against the 1.0.21 source:

* The output root (indir) is STABLE: it holds the ~325 MB
  one-time MAST text files under {indir}/data, and is
  recorded in <LATTE package>/_config.txt by the Mac setup
  (docs/external-tools-mac-setup.md). This wrapper READS
  _config.txt; it never rewrites it — a per-run indir would
  orphan the data files. A missing _config.txt means the
  setup was never done: the output reads "failed" with a
  clear reason.
* LATTE namespaces per target ({indir}/{tic}/) and writes
  the report to {indir}/{tic}/DV_report_{tic}.pdf. The
  wrapper copies the PDF into the run workdir — a stable
  artifact even if a later run overwrites LATTE's dir — and
  reports the copy's path.
* LATTE swallows per-target failures and exits 0 with no
  report. The wrapper checks for the PDF; no PDF means
  failed, whatever the exit code.
* The nested LATTE call gets its own timeout (the input's
  timeout_s minus a 60 s margin) so the wrapper kills LATTE
  itself before the runner's timeout kills the wrapper.
* BLS=no (the pipeline already ran BLS), model=no (pyaneti
  modelling is slow and optional), FFI from the input's
  ffi_mode flag (the desk driver sets it when the light
  curve is not SPOC 2-minute data).

Exit 0 means "an output JSON was written" (its `status`
field says whether LATTE completed, failed, or timed out);
a non-zero exit means the wrapper itself crashed before
writing one.
"""
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time

# Margin between the wrapper's own timeout on the nested
# LATTE call and the runner's timeout on the wrapper: the
# wrapper must kill LATTE itself, not be killed mid-write.
TIMEOUT_MARGIN_S = 60


def _installed_version(fallback):
    """The installed tessLATTE version, or the input's
    expected version with a warning when the distribution
    metadata is unavailable."""
    try:
        from importlib import metadata
        return metadata.version("tessLATTE"), None
    except Exception:  # noqa: BLE001 - any metadata failure
        return fallback, ("could not read the installed "
                          "tessLATTE version; reporting the "
                          "input's expected version")


def _latte_indir():
    """LATTE's configured output root, from _config.txt in
    the installed package dir. Returns (indir, error)."""
    try:
        import LATTE
    except ImportError as exc:
        return None, f"LATTE is not importable in this venv: {exc}"
    pkg_dir = os.path.dirname(os.path.abspath(LATTE.__file__))
    config_path = os.path.join(pkg_dir, "_config.txt")
    if not os.path.exists(config_path):
        return None, ("LATTE output path is not configured "
                      "(_config.txt missing in the LATTE "
                      "package dir) — run the Mac setup in "
                      "docs/external-tools-mac-setup.md first")
    with open(config_path) as fh:
        indir = fh.read().strip()
    if not indir or not os.path.isdir(indir):
        return None, (f"LATTE output path {indir!r} from "
                      f"_config.txt is not a directory")
    return indir, None


def _write_targetlist(path, tic, period, t0, sectors, ffi_mode):
    """The --targetlist CSV. LATTE parses `sectors` with
    ast.literal_eval, so it is written as a Python literal;
    BLS/model/FFI are read unconditionally, so all columns
    must be present."""
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["TICID", "period", "t0", "sectors",
                         "BLS", "model", "FFI"])
        writer.writerow([tic, repr(float(period)),
                         repr(float(t0)), repr(list(sectors)),
                         "no", "no", "yes" if ffi_mode else "no"])


def _output(tool_version, seed, config_hash, status, metrics,
            input_hashes, artifacts, warnings, wall_time_s,
            n_transits):
    return {
        "tool": "latte",
        "tool_version": tool_version,
        "seed": seed,
        "config_hash": config_hash,
        "status": status,
        "value": None,
        "metrics": metrics,
        "input_hashes": input_hashes,
        "artifacts": artifacts,
        "warnings": warnings,
        "wall_time_s": wall_time_s,
        "n_transits": n_transits,
    }


def run(input_path, output_path):
    """Run LATTE for the target in input_path; write the
    output JSON to output_path. Returns the output dict."""
    with open(input_path) as fh:
        inp = json.load(fh)
    workdir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(workdir, exist_ok=True)
    tic = str(inp["target"]["tic"])
    seed = inp["seed"]
    config_hash = inp["config_hash"]
    timeout_s = inp.get("timeout_s", 1800)
    n_transits = inp["signal"].get("n_transits")
    input_hashes = {
        "lightcurve": inp["lightcurve"]["input_hash"],
        "neighbours": inp["neighbours"]["input_hash"],
    }
    warnings = []
    tool_version, version_warning = _installed_version(
        inp.get("tool_version", "unknown"))
    if version_warning:
        warnings.append(version_warning)
    start = time.monotonic()

    def _failed(reason):
        warnings.append(reason)
        return _output(
            tool_version, seed, config_hash, "failed",
            {"report_pdf": None, "output_dir": None,
             "n_artifacts": 0, "latte_indir": None},
            input_hashes, [], warnings,
            time.monotonic() - start, n_transits)

    indir, err = _latte_indir()
    if err:
        return _failed(err)

    csv_path = os.path.join(workdir, "targetlist.csv")
    _write_targetlist(
        csv_path, tic, inp["signal"]["period_d"],
        inp["signal"]["t0_bjd"], inp["lightcurve"]["sectors"],
        bool(inp.get("ffi_mode", False)))
    target_dir = os.path.join(indir, tic)
    report_src = os.path.join(target_dir,
                              f"DV_report_{tic}.pdf")
    nested_timeout = max(60, int(timeout_s) - TIMEOUT_MARGIN_S)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "LATTE",
             f"--targetlist={csv_path}", "--o", "--noshow"],
            cwd=workdir, capture_output=True, text=True,
            timeout=nested_timeout)
    except subprocess.TimeoutExpired:
        warnings.append(
            f"LATTE timed out after {nested_timeout} s")
        return _output(
            tool_version, seed, config_hash, "timeout",
            {"report_pdf": None, "output_dir": target_dir,
             "n_artifacts": 0, "latte_indir": indir},
            input_hashes, [], warnings,
            time.monotonic() - start, n_transits)
    wall = time.monotonic() - start
    if proc.returncode != 0:
        warnings.append(
            f"LATTE exited {proc.returncode}: "
            f"{(proc.stderr or '').strip()[-500:]}")
    # The PDF is the arbiter, not the exit code: LATTE
    # swallows per-target failures and exits 0 with no report.
    if not os.path.exists(report_src):
        return _failed(
            f"LATTE produced no DV report for TIC {tic} "
            f"(expected {report_src})")
    report_dst = os.path.join(workdir, f"DV_report_{tic}.pdf")
    shutil.copy2(report_src, report_dst)
    try:
        n_artifacts = len(os.listdir(target_dir))
    except OSError:
        n_artifacts = 1
    return _output(
        tool_version, seed, config_hash, "completed",
        {"report_pdf": report_dst, "output_dir": target_dir,
         "n_artifacts": n_artifacts, "latte_indir": indir},
        input_hashes, [report_dst], warnings, wall, n_transits)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Drive LATTE for one target.")
    ap.add_argument("--input", required=True,
                    help="C-10 input JSON")
    ap.add_argument("--output", required=True,
                    help="C-10 output JSON to write")
    args = ap.parse_args(argv)
    out = run(args.input, args.output)
    with open(args.output, "w") as fh:
        json.dump(out, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
