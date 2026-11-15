"""Tests for bulk/flag_fraction_sweep.py (mask-fix follow-up M-5).

The sweep's headline claims, pinned on the --quick subset (clean,
random 20% all, blocks 20% all): no real transit is lost at any
flag fraction, and the v3 SDE cost is bounded. Exact numbers are
NOT pinned (they depend on the flag seeds); the claims are.
Determinism is pinned: two runs produce identical cells.jsonl.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bulk import flag_fraction_sweep as sweep  # noqa: E402


class TestFlagFractionSweep(unittest.TestCase):
    def _run_quick(self, out_dir):
        rc = sweep.main(["--out-dir", str(out_dir), "--quick"])
        self.assertEqual(rc, 0)
        summary = json.loads(
            (Path(out_dir) / "summary.json").read_text())
        cells = {c["cell"]: c for c in summary["cells"]}
        self.assertEqual(
            sorted(cells),
            sorted(["clean", "random 20% all", "blocks 20% all"]))
        return summary, cells

    def test_quick_subset_no_transit_lost(self):
        with tempfile.TemporaryDirectory() as td:
            _summary, cells = self._run_quick(td)
            for label, cell in cells.items():
                self.assertEqual(cell["bulk_v2"]["status"],
                                 "survivor", label)
                self.assertEqual(cell["bulk_v3"]["status"],
                                 "survivor", label)
                self.assertEqual(cell["bulk_v3"]["tier"], "A", label)

    def test_quick_subset_bounded_cost(self):
        # Random 20% flagging costs v3 at most 30% of the clean
        # SDE (measured ~17%); contiguous 20% blocks cost more
        # (measured ~43% SDE) but the transit still survives
        # with SDE >= 25 and MES >= 12 (tier-A bar is 9.0).
        with tempfile.TemporaryDirectory() as td:
            _summary, cells = self._run_quick(td)
            clean_sde = cells["clean"]["bulk_v3"]["sde"]
            rand = cells["random 20% all"]["bulk_v3"]
            self.assertGreaterEqual(rand["sde"], 0.7 * clean_sde)
            blocks = cells["blocks 20% all"]["bulk_v3"]
            self.assertGreaterEqual(blocks["sde"], 25.0)
            self.assertGreaterEqual(blocks["mes_pink"], 12.0)
            # Blocks cost more than random sprinkles at the same
            # fraction -- Gemini's topology critique, confirmed.
            self.assertLess(blocks["sde"], rand["sde"])

    def test_quick_subset_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            out1, out2 = Path(td) / "a", Path(td) / "b"
            self._run_quick(out1)
            self._run_quick(out2)
            cells1 = (out1 / "cells.jsonl").read_text()
            cells2 = (out2 / "cells.jsonl").read_text()
            self.assertEqual(cells1, cells2)


if __name__ == "__main__":
    unittest.main()
