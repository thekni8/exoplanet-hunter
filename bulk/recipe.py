"""Sector screen recipes — one YAML file drives a whole sector run.

A recipe is the single source of truth for a bulk-screen run: the
sector, the target window (Tmag + radius cuts), the target-list tag,
and the run shape (slice size, workers). Both the target-list build
(`bulk/build_target_list.py`) and the chunked screen driver
(`bulk/run_chunked.py`) read the same recipe, so the window that was
built is the window that gets screened — `run_chunked` verifies this
against the window file's recorded params and refuses to run on a
mismatch.

Precedence everywhere: CLI flags > recipe file > built-in defaults.
CLI flags that are not given leave the recipe value in place.

Schema (all keys optional except `sector`, which may also come from
--sector on the CLI):

    sector: 96                  # TESS sector number (int)
    window:
      min_mag: 10.0             # Tmag bright cut
      max_mag: 13.5             # Tmag faint cut
      min_rad: 0.2              # stellar radius lower cut (Rsun)
      max_rad: 0.8              # stellar radius upper cut (Rsun)
      require_radius: true      # drop stars with no radius measurement
      limit_ids: null           # cap on TIC ids at build time (smoke tests)
    tag: window_default         # target-list tag; window file is
                                # s<SSSS>_<tag>.json in the cache
    slice_size: 1250            # stars per chunked slice (checkpoint unit)
    dl_workers: 8               # parallel light-curve downloads
    workers: null               # BLS workers (null = bulk_screen default)
    k3: false                   # K=3 mask-and-re-search stage (4.1-1a):
                                # after each slice's K=1 screen, look
                                # behind pass-1 contaminants for a second
                                # signal (bulk/k3_driver.py). Default
                                # false — K=1 is the production screen
                                # until the driver is accepted (§2.1).

Deliberately NOT in the recipe: the survivor/tier thresholds
(SURVIVOR_SDE, TIER_A_MES, ...). Those are versioned calibration
constants in bulk_screen.py (see bulk/CALIBRATION_V1_1.md); changing
them per-run would make screens incomparable. To change a threshold,
change the code + calibration doc + the golden suite together.
"""

import re
from pathlib import Path

import yaml

DEFAULTS = {
    "sector": None,
    "window": {
        "min_mag": 10.0,
        "max_mag": 13.5,
        "min_rad": 0.2,
        "max_rad": 0.8,
        "require_radius": True,
        "limit_ids": None,
    },
    "tag": "window_default",
    "slice_size": 1250,
    "dl_workers": 8,
    "workers": None,
    # 4.1-1a: the K=3 stage is OFF by default. It is a recipe key
    # (not a bare CLI flag) so the resolved recipe hash — and
    # therefore the run/resume fingerprint — covers it: resuming
    # a K=1 run with K=3 (or vice versa) refuses, like any other
    # result-affecting change, instead of silently mixing K=1
    # and K=3 slices in one sector.
    "k3": False,
}

_TOP_KEYS = set(DEFAULTS)
_WINDOW_KEYS = set(DEFAULTS["window"])
_TAG_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


class RecipeError(ValueError):
    """Raised when a recipe file is missing, malformed, or invalid."""


def _merge(base, override):
    """Deep-merge override onto a copy of base (dicts merge by key)."""
    out = dict(base)
    for key, val in override.items():
        if (key in out and isinstance(out[key], dict)
                and isinstance(val, dict)):
            out[key] = _merge(out[key], val)
        else:
            out[key] = val
    return out


def _check(condition, message):
    if not condition:
        raise RecipeError(message)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate(recipe):
    """Validate a recipe dict in place (raises RecipeError). Keys
    starting with '_' are internal metadata (e.g. '_file') and are
    ignored by validation."""
    unknown = {k for k in recipe if not k.startswith("_")} - _TOP_KEYS
    _check(not unknown, f"unknown recipe keys: {sorted(unknown)}")
    win = recipe.get("window", {})
    _check(isinstance(win, dict), "'window' must be a mapping")
    unknown_w = set(win) - _WINDOW_KEYS
    _check(not unknown_w, f"unknown window keys: {sorted(unknown_w)}")

    sector = recipe.get("sector")
    _check(sector is None or (isinstance(sector, int)
                              and not isinstance(sector, bool)
                              and 1 <= sector <= 999),
           f"'sector' must be an integer 1..999, got {sector!r}")

    _check(_is_num(win["min_mag"]) and _is_num(win["max_mag"])
           and 0 <= win["min_mag"] <= win["max_mag"] <= 20,
           f"window mags must satisfy 0 <= min_mag <= max_mag <= 20, "
           f"got {win['min_mag']!r}..{win['max_mag']!r}")
    _check(_is_num(win["min_rad"]) and _is_num(win["max_rad"])
           and 0 < win["min_rad"] <= win["max_rad"],
           f"window radii must satisfy 0 < min_rad <= max_rad, "
           f"got {win['min_rad']!r}..{win['max_rad']!r}")
    _check(isinstance(win["require_radius"], bool),
           f"'require_radius' must be true/false, "
           f"got {win['require_radius']!r}")
    _check(win["limit_ids"] is None or (
        isinstance(win["limit_ids"], int)
        and not isinstance(win["limit_ids"], bool)
        and win["limit_ids"] > 0),
        f"'limit_ids' must be null or a positive integer, "
        f"got {win['limit_ids']!r}")

    _check(isinstance(recipe["tag"], str) and _TAG_RE.match(recipe["tag"]),
           f"'tag' must be a safe filename fragment, "
           f"got {recipe['tag']!r}")
    for key in ("slice_size", "dl_workers"):
        _check(isinstance(recipe[key], int)
               and not isinstance(recipe[key], bool)
               and recipe[key] > 0,
               f"'{key}' must be a positive integer, "
               f"got {recipe[key]!r}")
    _check(recipe["workers"] is None or (
        isinstance(recipe["workers"], int)
        and not isinstance(recipe["workers"], bool)
        and recipe["workers"] > 0),
        f"'workers' must be null or a positive integer, "
        f"got {recipe['workers']!r}")
    _check(isinstance(recipe["k3"], bool),
           f"'k3' must be true/false, got {recipe['k3']!r}")
    return recipe


def load_recipe(path):
    """Load + validate a recipe YAML file, defaults filled in."""
    path = Path(path)
    if not path.exists():
        raise RecipeError(f"recipe file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise RecipeError(f"recipe {path} is not valid YAML: {exc}") from exc
    if raw is None:
        raw = {}
    _check(isinstance(raw, dict),
           f"recipe {path} must be a YAML mapping at the top level")
    recipe = validate(_merge(DEFAULTS, raw))
    recipe["_file"] = str(path)
    return recipe


def default_recipe_path():
    """Path of the shipped default recipe (bulk/recipes/default.yaml)."""
    return Path(__file__).resolve().parent / "recipes" / "default.yaml"


def apply_overrides(recipe, overrides):
    """Apply CLI overrides (flat dict, None values ignored) and
    re-validate. CLI wins over the recipe file. Returns a new dict."""
    flat = {k: v for k, v in overrides.items() if v is not None}
    nested = {}
    for key, val in flat.items():
        if key in _WINDOW_KEYS:
            nested.setdefault("window", {})[key] = val
        elif key in _TOP_KEYS:
            nested[key] = val
        else:
            raise RecipeError(f"unknown override key: {key!r}")
    return validate(_merge(recipe, nested))
