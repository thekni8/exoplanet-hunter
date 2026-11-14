"""Same-product-selected test (Phase 1.2 follow-up F-14).

hunter._select_products and rawflux_check's pipeline-set
selection implement the SAME rule twice (most sectors wins,
SPOC > TESS-SPOC > QLP breaks ties, 120 s cadence preferred
within a sector, earliest sectors kept under a cap). If they
ever disagree, the gauntlet checks a different product set
than the pipeline searched — the raw-flux gate would be
vetting data the detection never saw.

These tests feed both implementations the same canned
author/sector layouts and assert they pick the same author
and the same sectors. hunter's MAST queries are mocked at
_search_author (canned lightkurve SearchResults built from
astropy Tables — no network); rawflux's selection is the
pure select_pipeline_set extracted from main() in F-14.

Known edge (documented, not fixed): rawflux caps the COUNT
at sector_cap, so two authors above the cap tie and priority
decides, while hunter counts all sectors. Agreement holds
when every author's count is at or below the cap.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hunter  # noqa: E402
import lightkurve as lk  # noqa: E402
from astropy.table import Table  # noqa: E402
from gauntlet.rawflux_check import select_pipeline_set  # noqa: E402

# hunter author name -> rawflux prefix
PFX = {"SPOC": "spoc", "TESS-SPOC": "tspc", "QLP": "qlp"}


def _canned_search(rows, author):
    """A lightkurve SearchResult over canned rows.

    rows: (sector, exptime) pairs. SearchResult's constructor
    sorts and annotates the table, so it needs the MAST-shaped
    columns it reads (distance, t_min, mission) as well as
    the ones _select_products reads (sequence_number, exptime).
    """
    return lk.SearchResult(Table({
        "sequence_number": [r[0] for r in rows],
        "exptime": [float(r[1]) for r in rows],
        "author": [author] * len(rows),
        "distance": [0.0] * len(rows),
        "t_min": [59000.0] * len(rows),
        "mission": ["TESS"] * len(rows)}))


def _hunter_pick(layout, max_sectors):
    """Run hunter._select_products on a canned layout.

    layout: {author: [(sector, exptime), ...]}. Returns
    (author, [sectors], {sector: exptime}) of the selected
    rows. _search_author is mocked; no network.
    """
    canned = {author: _canned_search(rows, author)
              for author, rows in layout.items()}

    def _fake_search(tic_id, author):
        return canned.get(author, _canned_search([], author))

    with mock.patch.object(hunter, "_search_author",
                           side_effect=_fake_search):
        picked = hunter._select_products(123456789, max_sectors)
    table = picked.table
    sectors = [int(s) for s in table["sequence_number"]]
    exptimes = {int(s): float(e) for s, e in
                zip(table["sequence_number"], table["exptime"])}
    author = str(table["author"][0]) if len(table) else None
    return author, sorted(sectors), exptimes


def _rawflux_pick(layout, sector_cap=20):
    """Run select_pipeline_set on the same layout.

    layout: {author: [(sector, exptime), ...]} — collapsed to
    {prefix: sorted distinct sectors}, the shape
    download_author returns (one npz per sector, sorted).
    """
    sets = {}
    for author, rows in layout.items():
        secs = sorted({s for s, _e in rows})
        if secs:
            sets[PFX[author]] = secs
    return select_pipeline_set(sets, sector_cap)


def _agree(testcase, layout, max_sectors=None, sector_cap=20):
    """Assert hunter and rawflux pick the same author+sectors."""
    h_author, h_sectors, _ex = _hunter_pick(layout, max_sectors)
    r_pfx, r_sectors = _rawflux_pick(layout, sector_cap)
    testcase.assertEqual(PFX[h_author], r_pfx)
    testcase.assertEqual(h_sectors, r_sectors)
    return h_author, h_sectors


class TestProductSelectionAgreement(unittest.TestCase):
    def test_qlp_most_sectors(self):
        # QLP has the most sectors — both must pick QLP, not
        # the higher-priority SPOC.
        layout = {"SPOC": [(1, 120.0), (2, 120.0)],
                  "TESS-SPOC": [(1, 120.0), (2, 120.0)],
                  "QLP": [(1, 120.0), (2, 120.0), (3, 120.0),
                          (4, 120.0)]}
        author, sectors = _agree(self, layout)
        self.assertEqual(author, "QLP")
        self.assertEqual(sectors, [1, 2, 3, 4])

    def test_tie_goes_to_spoc(self):
        # SPOC and TESS-SPOC tie at 3 sectors — priority
        # breaks the tie toward SPOC.
        layout = {"SPOC": [(1, 120.0), (2, 120.0), (3, 120.0)],
                  "TESS-SPOC": [(1, 120.0), (2, 120.0),
                                (3, 120.0)],
                  "QLP": [(1, 120.0)]}
        author, sectors = _agree(self, layout)
        self.assertEqual(author, "SPOC")
        self.assertEqual(sectors, [1, 2, 3])

    def test_tie_tspc_beats_qlp(self):
        layout = {"TESS-SPOC": [(1, 120.0), (2, 120.0)],
                  "QLP": [(1, 120.0), (2, 120.0)]}
        author, sectors = _agree(self, layout)
        self.assertEqual(author, "TESS-SPOC")
        self.assertEqual(sectors, [1, 2])

    def test_single_author(self):
        layout = {"QLP": [(5, 120.0), (6, 120.0)]}
        author, sectors = _agree(self, layout)
        self.assertEqual(author, "QLP")
        self.assertEqual(sectors, [5, 6])

    def test_sector_cap_agreement(self):
        # max_sectors=2 (hunter) vs sector_cap=2 (rawflux):
        # both keep the EARLIEST two sectors of the winner.
        layout = {"SPOC": [(1, 120.0), (2, 120.0), (3, 120.0),
                           (4, 120.0)]}
        author, sectors = _agree(self, layout, max_sectors=2,
                                 sector_cap=2)
        self.assertEqual(author, "SPOC")
        self.assertEqual(sectors, [1, 2])

    def test_hunter_prefers_120s_cadence(self):
        # Sector 1 has both a 20 s and a 120 s SPOC row —
        # hunter must pick the 120 s row (one product per
        # sector). rawflux's download_author applies the same
        # per-sector preference when it builds the sector
        # lists, so the sector SETS still agree.
        layout = {"SPOC": [(1, 20.0), (1, 120.0), (2, 120.0)]}
        author, sectors, exptimes = _hunter_pick(layout, None)
        self.assertEqual(author, "SPOC")
        self.assertEqual(sectors, [1, 2])
        self.assertEqual(exptimes[1], 120.0)
        self.assertEqual(exptimes[2], 120.0)
        _agree(self, layout)

    def test_no_sectors_is_empty(self):
        # rawflux-only: no pipeline has sectors.
        self.assertEqual(select_pipeline_set({}), (None, []))
        self.assertEqual(
            select_pipeline_set({"spoc": [], "qlp": []}),
            (None, []))


class TestSectorCapEdge(unittest.TestCase):
    def test_above_cap_counts_tie(self):
        # KNOWN EDGE (documented, not fixed): with a 20-sector
        # cap, SPOC's 21 sectors and QLP's 25 both count as
        # 20, so priority picks SPOC — while hunter counts all
        # sectors and picks QLP (25 > 21). This test pins both
        # behaviours so a future fix knows exactly what
        # changes; it is NOT an agreement assertion.
        layout = {"SPOC": [(s, 120.0) for s in range(1, 22)],
                  "QLP": [(s, 120.0) for s in range(1, 26)]}
        pfx, secs = _rawflux_pick(layout, sector_cap=20)
        self.assertEqual(pfx, "spoc")
        self.assertEqual(secs, list(range(1, 21)))
        h_author, _h_secs, _ex = _hunter_pick(layout, None)
        self.assertEqual(h_author, "QLP")


if __name__ == "__main__":
    unittest.main()
