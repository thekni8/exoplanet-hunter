# Census fixture — S97 case (Phase 1.2 follow-up F-1)

`s97_case.json` is the offline census fixture for the 180-arcsecond
neighbour search. The case is real: TIC 139526205's signal was a
photocopy of an eclipsing binary on TIC 139524628 at 66.5 arcseconds,
and the old 60-arcsecond census missed the host entirely (sector 97).
The TIC IDs, the 66.5-arcsecond separation, and the target Tmag (11.3,
from the blend fixture) are real. The coordinates are synthetic —
the target sits at (100.0, -65.0) and the neighbours are placed by
pure-declination offsets, which give exact great-circle separations
along the meridian — and the other rows' TIC IDs/Tmags are invented.

Rows:
- TIC 139526205 (target, 0″, Tmag 11.3)
- TIC 139524628 (the blend host, 66.5″, Tmag 12.1)
- TIC 100000001 (30″, Tmag 14.0) — inside both radii
- TIC 100000002 (150″, Tmag 15.2) — inside 180″ only
- TIC 100000003 (200″, Tmag 13.5) — outside both radii
- TIC 100000004 (45″, Tmag 19.5) — beyond the 18.5 magnitude limit
- TIC 100000005 (20″, Tmag null) — pins the missing-magnitude handling

The test (tests/test_census.py) asserts the census FINDS the host at
180″ and MISSES it at 60″ — the regression the 60″ default would
have failed.
