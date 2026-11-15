"""Out-of-process external-tool plumbing (Phase 2, 2B-1).

TRICERATOPS and LATTE run OUTSIDE the pipeline process, in
their own virtualenvs, behind this module — the C-10 design
doc's non-negotiable constraint 1. Neither tool's dependency
tree may leak into the pipeline environment, and the proof is
in the pins: TRICERATOPS 1.1.0 requires numpy<2 / scipy<1.14
(on Python < 3.13) while the pipeline pins numpy==2.5.4 /
scipy==1.18.1, and LATTE pins matplotlib==3.2.0 against the
pipeline's 3.11.2. A shared environment would silently move
the pipeline's numerics.

The runner spawns the tool, the tool writes JSON, the runner
reads JSON — no in-process imports, ever. The spawn is
guarded twice (Gemini's Phase 1.2 vote point: the tools'
memory/IPC on the 1.5–2 GB VM is unplanned):

* a wall-clock TIMEOUT (default 1800 s, the C-10 contract
  value) enforced by Popen + communicate — a hung tool is
  killed and the stage reads UNMEASURED. The kill is a
  process-GROUP kill (P-3): the child runs in its own
  session (start_new_session), so SIGKILL to the group
  takes the wrapper AND any children it spawned (LATTE
  shells out, TRICERATOPS forks workers) — killing only
  the wrapper would orphan them;
* a MEMORY CAP (default 2048 MB) enforced by RLIMIT_AS in
  the child before exec — an allocation past the cap raises
  MemoryError inside the child, which exits non-zero and the
  stage reads UNMEASURED. The cap is LINUX-ONLY (P-3):
  macOS/XNU counts the whole virtual address space against
  RLIMIT_AS, and numpy/scipy map generously at import, so a
  cap that is headroom on Linux would kill a healthy tool
  on the Mac. On macOS the cap is not applied and the run
  records memory_cap_applied=False — the timeout is the
  only guard there. The vote's preferred direction, an RSS
  watchdog, is future work (a P-16 step, when the Mac venvs
  exist to test it against).

On top of that, the tools are MAC-ONLY BY CONFIGURATION: the
tool venv paths in the policy point at the Mac
(/Volumes/NVME/pingu-jobs/exoplanet-hunter/venvs/...). On a
host where the venv python does not exist — the VM — the run
returns status "missing_venv" and the stage reads UNMEASURED
with a clear reason, never a crash. The VM never runs these
tools; the cap protects the Mac's other work, not the VM.

Wrapper protocol (gauntlet/tools/run_<tool>.py, executed by
the tool venv's python):

    python run_<tool>.py --input <input.json> --output <output.json>

The wrapper reads the C-10 input JSON, drives the tool, and
writes the C-10 output JSON. Exit 0 means "an output JSON was
written" (the output's own `status` field says whether the
TOOL completed, failed, or timed out); a non-zero exit means
the wrapper itself crashed and no output exists. The runner
must NOT trust the tool's exit code alone — LATTE swallows
per-target failures and exits 0 with no report, so the
wrapper checks for its own artifacts before declaring
success.

Two status layers, kept separate:

* ToolRunResult.status — the PROCESS outcome: "completed"
  (a parseable output JSON was produced), "failed" (no
  output: crash, non-zero exit, malformed JSON), "timeout"
  (the runner killed a hung tool), "missing_venv" (the tool
  venv is not present on this host).
* The output JSON's `status` field — the TOOL outcome:
  "completed" / "failed" / "timeout". The stage adapter
  (gauntlet/latte.py, gauntlet/triceratops.py) maps it.

A failure at either layer is UNMEASURED + EXEC_ERROR in the
adapter, never a pass and never a fail (C-10 constraint 4).
"""
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import resource
except ImportError:  # pragma: no cover - non-Unix hosts
    resource = None

# The C-10 design doc's example seed. The policy file
# (calibration/external_tools_v1.yaml) is the source of truth
# at runtime; this constant is the fallback when no policy is
# supplied. The seed is FIXED per tool config, not per target
# and not random per run — a re-run reproduces the number.
DEFAULT_SEED = 20261114
DEFAULT_TIMEOUT_S = 1800
DEFAULT_MEMORY_MB = 2048

STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_TIMEOUT = "timeout"
STATUS_MISSING_VENV = "missing_venv"

# Required keys of the C-10 input contract, per section.
_TARGET_KEYS = ("tic", "ra_deg", "dec_deg", "tmag",
                "star_radius_rsun", "star_mass_msun", "teff_k")
_SIGNAL_KEYS = ("period_d", "t0_bjd", "duration_h", "depth_frac",
                "n_transits")
_LIGHTCURVE_KEYS = ("path", "input_hash", "sectors", "cadence_s")
_NEIGHBOURS_KEYS = ("path", "input_hash", "radius_arcsec")


@dataclass(frozen=True)
class ToolConfig:
    """How to invoke one external tool."""
    tool: str              # "latte" | "triceratops"
    python: str            # path to the tool venv's python
    wrapper: str           # path to gauntlet/tools/run_<tool>.py
    timeout_s: int = DEFAULT_TIMEOUT_S
    memory_mb: int = DEFAULT_MEMORY_MB
    seed: int = DEFAULT_SEED
    tool_version: str = ""  # expected version; "" = don't check
    config_hash: str = ""   # sha256 of the tool config file


@dataclass(frozen=True)
class ToolRunResult:
    """The process outcome of one external-tool invocation."""
    status: str            # completed/failed/timeout/missing_venv
    output: dict | None    # parsed output JSON (None unless completed)
    wall_time_s: float
    returncode: int | None
    stderr_tail: str       # last ~2 KB of stderr, for the record
    # P-3: whether the RLIMIT_AS memory cap was actually
    # installed in the child. False on macOS (the cap is
    # Linux-only), when no cap was requested (memory_mb=0),
    # and when no process was spawned at all.
    memory_cap_applied: bool = False


def default_wrapper_path(tool):
    """The in-repo wrapper script for `tool`."""
    return str(Path(__file__).resolve().parent / "tools"
               / f"run_{tool}.py")


def sha256_file(path):
    """sha256 hex digest of a file's bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tool_config_hash(path):
    """sha256 of a tool config file — the C-10 `config_hash`."""
    return sha256_file(path)


def _require_keys(section, record, keys):
    missing = [k for k in keys if k not in record]
    if missing:
        raise ValueError(
            f"tool input {section} is missing key(s): "
            f"{', '.join(missing)}")


def build_tool_input(tool, tool_version, seed, config_hash,
                     target, signal, lightcurve, neighbours,
                     contrast_curve=None, timeout_s=DEFAULT_TIMEOUT_S):
    """Assemble the C-10 input JSON for one target.

    `target`, `signal`, `lightcurve` and `neighbours` are dicts
    carrying the contract's keys (validated here — a missing
    key is a caller bug and fails loud). `contrast_curve` is a
    {"path", "input_hash"} dict, or None when no high-resolution
    imaging exists (the tool degrades gracefully and must say
    so in its output warnings). Pass contrast_curve=False for
    LATTE: the C-10 contract gives LATTE no contrast_curve key
    at all (it does not use one).

    The signal ephemeris is always "refined" — the bulk period
    is never a valid tool input (AGENTS.md hard rule).
    """
    _require_keys("target", target, _TARGET_KEYS)
    _require_keys("signal", signal, _SIGNAL_KEYS)
    _require_keys("lightcurve", lightcurve, _LIGHTCURVE_KEYS)
    _require_keys("neighbours", neighbours, _NEIGHBOURS_KEYS)
    record = {
        "tool": tool,
        "tool_version": tool_version,
        "seed": seed,
        "config_hash": config_hash,
        "target": {k: target[k] for k in _TARGET_KEYS},
        "signal": {k: signal[k] for k in _SIGNAL_KEYS},
        "lightcurve": {k: lightcurve[k] for k in _LIGHTCURVE_KEYS},
        "neighbours": {k: neighbours[k] for k in _NEIGHBOURS_KEYS},
        "timeout_s": timeout_s,
    }
    record["signal"]["ephemeris"] = "refined"
    if contrast_curve is not False:
        if contrast_curve is None:
            record["contrast_curve"] = {"path": None,
                                        "input_hash": None}
        else:
            _require_keys("contrast_curve", contrast_curve,
                          ("path", "input_hash"))
            record["contrast_curve"] = {
                "path": contrast_curve["path"],
                "input_hash": contrast_curve["input_hash"],
            }
    return record


def _memory_cap_preexec(memory_mb, platform=None):
    """preexec_fn setting RLIMIT_AS in the child (Linux only).

    Returns None when the resource module is unavailable, no
    cap was requested, or the host is not Linux — the caller
    records that the cap did not apply
    (ToolRunResult.memory_cap_applied). The Linux-only guard
    is P-3 (Phase 2 vote): macOS/XNU counts the whole
    virtual address space against RLIMIT_AS, and numpy/scipy
    map generously at import, so a 2048 MB cap that is
    headroom on Linux would kill a healthy tool on the Mac.
    `platform` is a test seam (default: sys.platform).
    """
    if platform is None:
        platform = sys.platform
    if resource is None or not memory_mb:
        return None
    if not platform.startswith("linux"):
        return None

    limit = int(memory_mb) * 1024 * 1024

    def _cap():
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))

    return _cap


def run_external_tool(config, input_data, work_dir):
    """Run one external tool out of process. Never raises for a
    tool-side failure — every failure mode is a status.

    Writes input.json into work_dir, invokes
    [python, wrapper, --input, --output] under the timeout and
    memory cap, and parses output.json. A missing venv python
    returns "missing_venv" without spawning anything.

    Fault modes (P-13 — every one is a status, never a raise
    and never a silent PASS):
      venv python missing      -> missing_venv (no spawn)
      wrapper missing          -> failed
      spawn fails (OSError)    -> failed ("could not spawn";
                                  e.g. the venv broke mid-run)
      child exits non-zero     -> failed (returncode kept)
      child killed by signal   -> failed (returncode < 0, e.g.
                                  -9 for SIGKILL / OOM-killer)
      timeout                  -> timeout (the whole process
                                  group is SIGKILLed, P-3)
      exit 0, no output.json   -> failed
      output.json malformed    -> failed ("unreadable")
      output.json not an object-> failed
    Stdout is never parsed: garbage on stdout with a valid
    output.json still completes. The adapters map failed /
    timeout / missing_venv to UNMEASURED + EXEC_ERROR (never
    a pass — see the P-2 verdict-invariance test).
    """
    work_dir = str(work_dir)
    os.makedirs(work_dir, exist_ok=True)
    input_path = os.path.join(work_dir, "input.json")
    output_path = os.path.join(work_dir, "output.json")
    with open(input_path, "w") as fh:
        json.dump(input_data, fh, indent=2, default=str)

    if not os.path.exists(config.python):
        return ToolRunResult(
            STATUS_MISSING_VENV, None, 0.0, None,
            f"tool venv python not found: {config.python} "
            f"(this tool runs on the Mac; see "
            f"docs/external-tools-mac-setup.md)")
    if not os.path.exists(config.wrapper):
        return ToolRunResult(
            STATUS_FAILED, None, 0.0, None,
            f"tool wrapper not found: {config.wrapper}")

    cmd = [config.python, config.wrapper,
           "--input", input_path, "--output", output_path]
    cap_fn = _memory_cap_preexec(config.memory_mb)
    cap_applied = cap_fn is not None
    start = time.monotonic()
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
            preexec_fn=cap_fn)
    except OSError as exc:
        # The spawn itself failed (e.g. the python binary is
        # not executable) — a status, not a raise.
        return ToolRunResult(
            STATUS_FAILED, None, time.monotonic() - start, None,
            f"could not spawn the tool: {exc}")
    try:
        _out, err = proc.communicate(timeout=config.timeout_s)
    except subprocess.TimeoutExpired:
        # Kill the WHOLE process group (P-3): the wrapper may
        # have spawned children, and killing only the wrapper
        # would orphan them. start_new_session put the child
        # in its own group with the wrapper as leader, so
        # SIGKILL to the group takes the wrapper and its
        # children together. The group may already be gone
        # (the child exited between the timeout and the kill)
        # — that is not an error.
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        _out, err = proc.communicate()
        return ToolRunResult(
            STATUS_TIMEOUT, None, time.monotonic() - start, None,
            ((err or "")
             or f"timed out after {config.timeout_s} s")[-2048:],
            memory_cap_applied=cap_applied)
    wall = time.monotonic() - start
    stderr_tail = (err or "")[-2048:]
    if proc.returncode != 0:
        return ToolRunResult(
            STATUS_FAILED, None, wall, proc.returncode,
            stderr_tail or f"wrapper exited {proc.returncode}",
            memory_cap_applied=cap_applied)
    if not os.path.exists(output_path):
        return ToolRunResult(
            STATUS_FAILED, None, wall, proc.returncode,
            "wrapper exited 0 but wrote no output JSON",
            memory_cap_applied=cap_applied)
    try:
        with open(output_path) as fh:
            output = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        return ToolRunResult(
            STATUS_FAILED, None, wall, proc.returncode,
            f"output JSON unreadable: {exc}",
            memory_cap_applied=cap_applied)
    if not isinstance(output, dict):
        return ToolRunResult(
            STATUS_FAILED, None, wall, proc.returncode,
            "output JSON is not an object",
            memory_cap_applied=cap_applied)
    return ToolRunResult(STATUS_COMPLETED, output, wall,
                         proc.returncode, stderr_tail,
                         memory_cap_applied=cap_applied)


def python_executable():
    """The current interpreter — the test seam for fake tools."""
    return sys.executable


# Tools the policy may configure, in run order (LATTE first:
# cheaper, and its report is useful even when TRICERATOPS
# later fails).
KNOWN_TOOLS = ("latte", "triceratops")


def load_external_tool_configs(policy_name="external_tools_v1",
                               repo_root=None):
    """ToolConfigs from a versioned policy file (default
    calibration/external_tools_v1.yaml, registry-verified by
    the calibration loader). Returns {tool: ToolConfig} for
    every tool the policy configures. The config_hash is the
    policy file's own sha256 — the policy IS the tool config.
    Wrapper paths are resolved against repo_root (default:
    the repo root above gauntlet/); absolute paths pass
    through unchanged. Per-tool timeout_s / memory_mb / seed
    override the shared settings when present.
    """
    from calibration import load_profile, profile_sha256
    if repo_root is None:
        repo_root = str(Path(__file__).resolve().parent.parent)
    policy = load_profile(policy_name)
    config_hash = profile_sha256(policy_name)
    configs = {}
    for tool in KNOWN_TOOLS:
        section = policy.get(tool)
        if not isinstance(section, dict):
            continue
        venv_python = section.get("venv_python")
        wrapper = section.get("wrapper")
        if not venv_python or not wrapper:
            continue
        if not os.path.isabs(wrapper):
            wrapper = os.path.join(repo_root, wrapper)
        configs[tool] = ToolConfig(
            tool=tool,
            python=str(venv_python),
            wrapper=str(wrapper),
            timeout_s=int(section.get("timeout_s",
                                      policy.get("timeout_s",
                                                 DEFAULT_TIMEOUT_S))),
            memory_mb=int(section.get("memory_mb",
                                      policy.get("memory_mb",
                                                 DEFAULT_MEMORY_MB))),
            seed=int(section.get("seed",
                                 policy.get("seed", DEFAULT_SEED))),
            tool_version=str(section.get("tool_version", "")),
            config_hash=config_hash)
    return configs
