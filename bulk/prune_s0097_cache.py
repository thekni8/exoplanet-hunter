"""Prune the sector-97 download cache: keep survivor FITS, delete the rest.

Usage: python3 prune_s0097_cache.py <cache_s0097_dir> <keep_tics.txt>
Safety: refuses to run unless the keep file holds >= 1000 TICs (a
truncated keep file must never cause mass deletion) and the target dir
is named s0097. Only *.fits files in that dir are touched.
"""
import os
import sys


def main():
    cache_dir, keep_file = sys.argv[1], sys.argv[2]
    assert os.path.basename(os.path.normpath(cache_dir)) == "s0097", \
        "target dir must be s0097"
    with open(keep_file) as fh:
        keep = set(l.strip() for l in fh if l.strip())
    assert len(keep) >= 1000, f"keep file too small ({len(keep)} TICs)"
    files = [f for f in os.listdir(cache_dir) if f.endswith(".fits")]
    n_before = len(files)
    bytes_before = sum(os.path.getsize(os.path.join(cache_dir, f))
                       for f in files)
    deleted, kept, freed = 0, 0, 0
    for f in files:
        path = os.path.join(cache_dir, f)
        if f[:-5] in keep:
            kept += 1
        else:
            freed += os.path.getsize(path)
            os.remove(path)
            deleted += 1
    print(f"before: {n_before} files, {bytes_before / 1e9:.1f} GB")
    print(f"kept: {kept} survivor FITS")
    print(f"deleted: {deleted} files, {freed / 1e9:.1f} GB freed")
    after = [f for f in os.listdir(cache_dir) if f.endswith(".fits")]
    print(f"after: {len(after)} files")
    assert len(after) == kept, "count mismatch after prune"


if __name__ == "__main__":
    main()
