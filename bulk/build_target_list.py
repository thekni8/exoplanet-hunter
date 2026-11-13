"""Build/validate a sector star list via bulk_screen's target-list
method (QLP target-list CSV + batched TIC lookups, cached + resumable).

The build is driven by a YAML recipe (bulk/recipes/*.yaml) — same
recipe the chunked screen driver reads, so the window built is the
window screened. CLI flags override the recipe; --sector may come
from either.

Examples:
  # Standard window for a sector, from the default recipe
  python bulk/build_target_list.py --sector 98
  # Rabtsevich recount check (his rule: Tmag<=11.5, no radius cut)
  python bulk/build_target_list.py --sector 98 --min-mag 0 \
      --max-mag 11.5 --no-require-radius
  # Smoke test: first 2,000 IDs only
  python bulk/build_target_list.py --recipe bulk/recipes/smoke.yaml
Writes <cache>/target_lists/sXXXX_<tag>.json (stats + TICs).
"""
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bulk.recipe import (RecipeError, apply_overrides,
                         default_recipe_path, load_recipe)
import bulk_screen as bs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe", default=str(default_recipe_path()),
                    help="YAML recipe file (default: bulk/recipes/default.yaml)")
    ap.add_argument("--sector", type=int, default=None,
                    help="TESS sector (overrides the recipe)")
    ap.add_argument("--min-mag", type=float, default=None)
    ap.add_argument("--max-mag", type=float, default=None)
    ap.add_argument("--min-rad", type=float, default=None)
    ap.add_argument("--max-rad", type=float, default=None)
    ap.add_argument("--require-radius",
                    action=argparse.BooleanOptionalAction, default=None)
    ap.add_argument("--limit-ids", type=int, default=None)
    ap.add_argument("--cache-dir", default=str(ROOT / "bulk" / "cache"))
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()
    try:
        recipe = load_recipe(args.recipe)
        recipe = apply_overrides(recipe, {
            "sector": args.sector, "min_mag": args.min_mag,
            "max_mag": args.max_mag, "min_rad": args.min_rad,
            "max_rad": args.max_rad,
            "require_radius": args.require_radius,
            "limit_ids": args.limit_ids, "tag": args.tag,
        })
    except RecipeError as exc:
        ap.error(str(exc))
    sector = recipe["sector"]
    if sector is None:
        ap.error("--sector is required (or set sector: in the recipe)")
    win = recipe["window"]

    stars, stats = bs.target_list_star_list(
        sector, win["min_mag"], win["max_mag"], win["min_rad"],
        win["max_rad"], args.cache_dir,
        require_radius=win["require_radius"],
        limit_ids=win["limit_ids"])
    stats["window"] = {"min_mag": win["min_mag"],
                       "max_mag": win["max_mag"],
                       "min_rad": win["min_rad"],
                       "max_rad": win["max_rad"],
                       "require_radius": win["require_radius"],
                       "limit_ids": win["limit_ids"]}
    stats["recipe"] = {"file": recipe["_file"], "tag": recipe["tag"]}
    out = (Path(args.cache_dir) / "target_lists" /
           f"s{sector:04d}_{recipe['tag']}.json")
    out.write_text(json.dumps(
        {"stats": stats, "tics": [s["tic"] for s in stars]}, indent=1))
    print(json.dumps(stats, indent=1))
    print("wrote", out)


if __name__ == "__main__":
    main()
