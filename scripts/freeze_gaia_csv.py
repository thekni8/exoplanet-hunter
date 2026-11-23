#!/usr/bin/env python3
"""Adopt an existing Gaia background CSV into a freeze dir.

M6 (2026-11-23, proven): a live Gaia TAP query returns the
same star set in a different ROW ORDER every time, and
TRICERATOPS's MC draws are order-sensitive, so per-seed
FPPs jitter up to ~0.2% between identical runs. Exact FPP
reproduction requires freezing the Gaia CSV BYTES, not
just the seed.

This script is the adoption path for a CSV that already
exists (e.g. the Nov-16 cached CSV that reproduces 4.1-6
to 16 digits): it copies the bytes verbatim into the
freeze dir and writes the sha256 provenance file beside
them. The wrapper (gauntlet/tools/run_triceratops.py)
freezes live-queried CSVs itself when the input names
gaia_freeze_dir, and seeds a frozen CSV when the input
names frozen_gaia_csv.

A frozen CSV is IMMUTABLE: if the freeze dir already
holds a CSV for this TIC with different bytes, the
existing file is kept untouched and this script exits 1
(the run's FPP is unaffected either way — the caller
decides what the mismatch means).

Usage:
    python scripts/freeze_gaia_csv.py \
        --csv /path/to/183537452_gaia_background.csv \
        --freeze-dir /path/to/record-dir \
        [--tic 183537452] [--source "Nov-16 cached CSV"]

Exit codes: 0 = frozen (or already present, identical);
1 = freeze dir already holds a DIFFERENT CSV for this
TIC (existing bytes kept); 2 = error (missing/empty
source, unreadable file).
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gauntlet.tools.run_triceratops import (  # noqa: E402
    freeze_gaia_csv)


def _infer_tic(csv_path):
    """The TIC id from a <tic>_gaia_background.csv
    filename, or None when the name does not match."""
    m = re.match(r"(\d+)_gaia_background\.csv$",
                 os.path.basename(csv_path))
    return m.group(1) if m else None


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Freeze a Gaia background CSV's bytes "
                    "into a freeze dir with sha256 "
                    "provenance.")
    ap.add_argument("--csv", required=True,
                    help="the Gaia background CSV to freeze")
    ap.add_argument("--freeze-dir", required=True,
                    help="directory to freeze into (the "
                         "target's record dir)")
    ap.add_argument("--tic", default=None,
                    help="TIC id (inferred from the CSV "
                         "filename when omitted)")
    ap.add_argument("--source", default="adopted existing CSV",
                    help="provenance source string")
    args = ap.parse_args(argv)
    tic = args.tic or _infer_tic(args.csv)
    if not tic:
        print("cannot infer the TIC id from the CSV "
              "filename; pass --tic", file=sys.stderr)
        return 2
    try:
        result = freeze_gaia_csv(args.csv, args.freeze_dir,
                                 tic, source=args.source)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        print(f"freeze failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    if result["status"] == "kept-existing-different":
        print("freeze dir already holds a DIFFERENT Gaia "
              "CSV for this TIC; kept the existing frozen "
              "bytes", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
