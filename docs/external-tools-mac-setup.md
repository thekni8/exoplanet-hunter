# External tools — Mac setup (Phase 2, 2B/2C)

LATTE and TRICERATOPS run **on the Mac only**, each in its own
virtualenv, driven out of process by the desk gauntlet
(`gauntlet/external_tool.py`). The VM never runs them: the
venv paths in `calibration/external_tools_v1.yaml` point at
the Mac, and on any host without them the tool stage reads
UNMEASURED (`missing_venv`), never a crash.

**Nothing here is run by the Phase 2 build.** These are
Dev-visible commands to run on the Mac (or approve) once the
Phase 2 vote ratifies the tools. The venvs live on the NVMe
SSD alongside the pipeline — never on the Mac's internal
disk, per Dev's rules.

## Paths (must match `calibration/external_tools_v1.yaml`)

| Tool | venv python |
|---|---|
| LATTE | `/Volumes/NVME/pingu-jobs/exoplanet-hunter/venvs/latte/bin/python` |
| TRICERATOPS | `/Volumes/NVME/pingu-jobs/exoplanet-hunter/venvs/triceratops/bin/python` |

LATTE's output root (stable — it holds the ~325 MB one-time
MAST text files under `{indir}/data`):

```
/Volumes/NVME/pingu-jobs/exoplanet-hunter/latte-out/
```

## 0. Check what Pythons the Mac has

```bash
ls /usr/local/bin/python* /opt/homebrew/bin/python* /Library/Frameworks/Python.framework/Versions/ 2>/dev/null
python3 --version
```

The two tools need **different, older Pythons** than the
pipeline's 3.12 — this is the main setup risk (see below).

## 1. LATTE venv (Python 3.8)

LATTE 1.0.21 pins `matplotlib==3.2.0` and `astropy<=4.0`,
which have **no wheels past CPython 3.8**. The venv needs
Python 3.8. On the Apple Silicon Mac that means the Intel
python.org 3.8 installer running under Rosetta 2 (if
Rosetta is still available on this macOS), or a pyenv 3.8
build. If Python 3.8 cannot be installed, LATTE cannot run
as pinned — the fallbacks are (a) relax the matplotlib /
astropy pins and verify LATTE still produces its report
(deviation from the author's pins, needs a verification run
on a known target), or (b) drop LATTE: the in-repo checks
already cover odd/even, centroid, pixel and shape. That
choice is the Phase 2 vote's, not this doc's.

```bash
cd /Volumes/NVME/pingu-jobs/exoplanet-hunter
mkdir -p venvs latte-out

# Python 3.8 venv (adjust the interpreter path to the 3.8
# install actually present on the Mac)
/Library/Frameworks/Python.framework/Versions/3.8/bin/python3.8 \
  -m venv venvs/latte
venvs/latte/bin/pip install --upgrade pip
venvs/latte/bin/pip install "tessLATTE==1.0.21"

# Smoke check: tkinter must import (python.org macOS
# installers ship it; a Homebrew python needs python-tk)
venvs/latte/bin/python -c "import tkinter, LATTE; print('latte ok')"
```

First run — point LATTE at its output root and download the
one-time ~325 MB text files. `_config.txt` lives in the
LATTE package dir and holds just the path; writing it
directly avoids the interactive prompt:

```bash
LATTE_DIR=$(venvs/latte/bin/python -c "import LATTE, os; print(os.path.dirname(LATTE.__file__))")
echo "/Volumes/NVME/pingu-jobs/exoplanet-hunter/latte-out" > "$LATTE_DIR/_config.txt"
```

Then verify on a known planet (WASP-29b, TIC 183537452 —
the v2 rescore recovered it). One-row targetlist CSV:

```csv
TICID,period,t0,sectors,BLS,model,FFI
183537452,3.9227,3910.0997,"[96]",no,no,no
```

```bash
# --new-data downloads the ~325 MB text files on this first run
caffeinate -s -i venvs/latte/bin/python -m LATTE \
  --targetlist=/tmp/latte-verify.csv --o --noshow --new-data
ls latte-out/183537452/DV_report_183537452.pdf
```

Success = the DV report PDF exists. (SSL certificate errors
are LATTE's documented first-run gotcha: check with
`venvs/latte/bin/python -m tess_stars2px -t 261136679`.)

## 2. TRICERATOPS venv (Python 3.11)

TRICERATOPS 1.1.0 pins `numpy<2` / `scipy<1.14` on Python
< 3.13, which have wheels through 3.12 — but `pytransit==2.2`
and `celerite>=0.4.0` are older builds, so Python 3.11 is
the safer target (fall back to 3.10 if the 3.11 install
fails on a missing wheel).

```bash
cd /Volumes/NVME/pingu-jobs/exoplanet-hunter
python3.11 -m venv venvs/triceratops
venvs/triceratops/bin/pip install --upgrade pip
venvs/triceratops/bin/pip install "triceratops==1.1.0"

# Smoke check
venvs/triceratops/bin/python -c \
  "from triceratops.triceratops import target; print('triceratops ok')"
```

Verification is the wrapper run on a known planet + a known
EB (the C-10 acceptance test: low FPP on the planet, high
FPP on the EB) — via the desk CLI once 2C lands:

```bash
# Planet: WASP-29b (TIC 183537452) — expect FPP < 0.015
# EB: TIC 308851365 — expect FPP > 0.5
caffeinate -s -i .venv/bin/python scripts/desk_gauntlet.py 183537452 \
  --period 3.9227 --t0 3910.0997 --duration 2.208 --depth 0.83 \
  --sector 96 --external-tools
```

## 3. Lockfiles (after a verified install)

Once each venv installs and verifies, freeze it the C-9 way
(`scripts/make_lockfile.py`, same pattern as
`requirements.lock`): `requirements-latte.lock` and
`requirements-triceratops.lock`, with the install command +
the verification target recorded in the lockfile header.
The lockfile freezes the venv that works — build it after
verification, not before.

## 4. How the driver finds the tools

`scripts/desk_gauntlet.py --external-tools` loads
`calibration/external_tools_v1.yaml` (registry-verified) and
passes the ToolConfigs to the driver. The driver runs the
tools after pass 2, only on a survivor no stage failed, and
records their StageResults in `desk_natives.json` under
`extra_evidence.external_tools` (evidence only — they never
feed the verdict until the vote ratifies the thresholds).
Each invocation is capped at 1800 s / 2048 MB by the runner.

## Troubleshooting

- `tool venv python not found` in a desk run: the venv was
  never created on this host, or the policy path is wrong.
  On the VM this is expected — the tools are Mac-only.
- `LATTE output path is not configured`: `_config.txt` is
  missing — repeat the step 1 `_config.txt` write.
- `LATTE produced no DV report`: LATTE ran but the target
  failed (no 2-minute data for a normal-mode run, or no
  transit time inside the data). Check whether the target
  needs FFI mode (the driver sets it from the light-curve
  product) and whether the refined T0 sits inside an
  observed sector.
- A killed wrapper can leave a LATTE process behind only if
  the runner's timeout fires first; the wrapper kills LATTE
  itself 60 s before that. Strays: `pkill -f "m LATTE"`.
