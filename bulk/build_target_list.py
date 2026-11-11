"""Build/validate a sector star list via bulk_screen's target-list
method (QLP target-list CSV + batched TIC lookups, cached + resumable).

Examples:
  # Rabtsevich recount check (his rule: Tmag<=11.5, no radius cut)
  python bulk/build_target_list.py --sector 98 --min-mag 0 \
      --max-mag 11.5 --no-require-radius
  # Our screening window for sector 1, first 20k IDs only (smoke test)
  python bulk/build_target_list.py --sector 1 --limit-ids 20000
Writes <cache>/target_lists/sXXXX_window_<tag>.json (stats + TICs).
"""
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import bulk_screen as bs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sector", type=int, required=True)
    ap.add_argument("--min-mag", type=float, default=10.0)
    ap.add_argument("--max-mag", type=float, default=13.5)
    ap.add_argument("--min-rad", type=float, default=0.2)
    ap.add_argument("--max-rad", type=float, default=0.8)
    ap.add_argument("--no-require-radius", action="store_true")
    ap.add_argument("--limit-ids", type=int, default=None)
    ap.add_argument("--cache-dir", default=str(ROOT / "bulk" / "cache"))
    ap.add_argument("--tag", default="window")
    args = ap.parse_args()

    stars, stats = bs.target_list_star_list(
        args.sector, args.min_mag, args.max_mag, args.min_rad,
        args.max_rad, args.cache_dir, require_radius=not args.no_require_radius,
        limit_ids=args.limit_ids)
    stats["window"] = {"min_mag": args.min_mag, "max_mag": args.max_mag,
                       "min_rad": args.min_rad, "max_rad": args.max_rad,
                       "require_radius": not args.no_require_radius,
                       "limit_ids": args.limit_ids}
    out = (Path(args.cache_dir) / "target_lists" /
           f"s{args.sector:04d}_{args.tag}.json")
    out.write_text(json.dumps(
        {"stats": stats, "tics": [s["tic"] for s in stars]}, indent=1))
    print(json.dumps(stats, indent=1))
    print("wrote", out)


if __name__ == "__main__":
    main()
