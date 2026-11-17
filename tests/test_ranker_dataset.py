"""3A dataset-builder tests (Phase 3, P3-17).

Offline, tiny synthetic data files in a temp dir — never the
real data files. Pins the training design: three-class labels,
TIC-grouped splits, the 3B-removed exclusions, the held-out
known planets, and the balanced class weights.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bulk import ranker_dataset as rd  # noqa: E402


def _screen(sde=20.0, tier="B"):
    return {
        "sde": sde, "mes_pink": 12.0, "status": "survivor",
        "tier": tier, "period_days": 3.0, "depth_percent": 0.5,
        "flags": [], "odd_even_ratio": 0.9,
        "search_health": "VALID_DETECTION", "n_events_found": 3,
        "n_strong_events": 2, "max_event_snr": 8.0, "alts": [],
    }


def _row(tic, period=3.0, t0=3910.0, tier="B", sde=20.0):
    return {
        "tic": str(tic), "period_days": period, "t0_btjd": t0,
        "duration_hours": 3.0, "depth_percent": 0.5, "sde": sde,
        "sector": 96, "flags": [], "odd_even_ratio": 0.9,
        "secondary_depth_percent": 0.01, "near_systematic": False,
        "status": "survivor", "mes_pink": 12.0, "n_events": 3,
        "n_strong_events": 2, "max_event_snr": 8.0, "tier": tier,
    }


class TestDatasetBuilder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        # Campaign: 2 hosts (1 train, 1 test), mixed trials.
        hosts = [
            {"tic": "100", "sector": 96, "split": "train",
             "complete": True, "trials": [
                 {"trial_id": "t1", "kind": "planet",
                  "label_class": "planet_like",
                  "label_fine": "planet_like",
                  "recovered": True, "screen": _screen()},
                 {"trial_id": "t2", "kind": "eb",
                  "label_class": "astrophysical_fp",
                  "label_fine": "confirmed_eb",
                  "recovered": True, "screen": _screen()},
                 {"trial_id": "t3", "kind": "planet",
                  "label_class": "planet_like",
                  "label_fine": "planet_like",
                  "recovered": False, "screen": _screen()},
             ]},
            {"tic": "200", "sector": 95, "split": "test",
             "complete": True, "trials": [
                 {"trial_id": "t4", "kind": "sinusoid",
                  "label_class": "astrophysical_fp",
                  "label_fine": "known_variable",
                  "recovered": True, "screen": _screen()},
             ]},
        ]
        with open(self.dir / "injections.jsonl", "w") as fh:
            for h in hosts:
                fh.write(json.dumps(h) + "\n")
        # Rescore: 1 labelled EB + 1 held-out planet + 21 rows
        # sharing one (P, T0) epoch cluster + 5 ordinary rows.
        rescore = [
            _row("300"),  # labelled EB (LEDGER)
            _row("183537452"),  # WASP-29b — held out
            _row("400", period=20.0),  # P=20.0 single — excluded
        ]
        for i in range(21):
            rescore.append(_row(500 + i, period=13.2, t0=3920.0))
        for i in range(5):
            rescore.append(_row(600 + i, period=2.0 + i * 0.1))
        with open(self.dir / "rescore.jsonl", "w") as fh:
            for r in rescore:
                fh.write(json.dumps(r) + "\n")
        # Null: 3 ordinary rows.
        with open(self.dir / "null.jsonl", "w") as fh:
            for i in range(3):
                fh.write(json.dumps(
                    _row(700 + i, period=4.0 + i)) + "\n")
        labels = {"300": "eb"}
        with open(self.dir / "labels.json", "w") as fh:
            json.dump(labels, fh)
        ledger = (
            "# ledger\n\n"
            "| 1 | 300 | 50.0 | 1.0 | 1.0 | KILLED — eclipsing binary"
            " | V-shaped |\n"
        )
        (self.dir / "LEDGER.md").write_text(ledger)
        self.paths = {
            "campaign": str(self.dir / "injections.jsonl"),
            "rescore": str(self.dir / "rescore.jsonl"),
            "null": str(self.dir / "null.jsonl"),
            "labels": str(self.dir / "labels.json"),
            "ledger": str(self.dir / "LEDGER.md"),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _build(self, **kw):
        return rd.build_dataset(
            self.paths, seed=7, n_null_sample=3,
            n_random_sample=5, **kw)

    def test_campaign_rows_recovered_only(self):
        ds = self._build()
        camp = [r for r in ds["rows"] if r["source"] == "campaign"]
        self.assertEqual(len(camp), 3)  # t1, t2, t4 (t3 unrecovered)
        by_id = {r["trial_id"]: r for r in camp}
        self.assertEqual(by_id["t1"]["label"], "planet")
        self.assertEqual(by_id["t2"]["label"], "astro_fp")
        self.assertEqual(by_id["t2"]["sublabel"], "confirmed_eb")
        self.assertEqual(by_id["t4"]["label"], "astro_fp")
        self.assertEqual(by_id["t4"]["sublabel"], "known_variable")

    def test_campaign_host_split_inherited(self):
        ds = self._build()
        by_id = {r["trial_id"]: r for r in ds["rows"]
                 if r["source"] == "campaign"}
        self.assertEqual(by_id["t1"]["split"], "train")
        self.assertEqual(by_id["t4"]["split"], "test")

    def test_gauntlet_finer_class(self):
        ds = self._build()
        lead = [r for r in ds["rows"] if r["tic"] == "300"]
        self.assertEqual(len(lead), 1)
        self.assertEqual(lead[0]["label"], "astro_fp")
        self.assertEqual(lead[0]["sublabel"], "confirmed_eb")
        self.assertEqual(lead[0]["ledger_rank"], 1)

    def test_held_out_planets_never_trained(self):
        ds = self._build()
        self.assertEqual(
            [r for r in ds["rows"] if r["tic"] == "183537452"], [])
        self.assertEqual([r["tic"] for r in ds["heldout"]],
                         ["183537452"])

    def test_p20_and_cluster_excluded_from_negatives(self):
        ds = self._build()
        negs = {r["tic"] for r in ds["rows"]
                if r["source"] in ("random_survivor", "inverted_null")}
        self.assertNotIn("400", negs)  # P = 20.0
        for i in range(21):
            self.assertNotIn(str(500 + i), negs)  # epoch cluster
        self.assertEqual(ds["exclusions"]["rescore_p20"], 1)
        self.assertEqual(ds["exclusions"]["rescore_cluster"], 21)

    def test_no_tic_straddles(self):
        ds = self._build()
        seen = {}
        for row in ds["rows"]:
            self.assertEqual(
                seen.setdefault(row["tic"], row["split"]),
                row["split"])

    def test_class_weights_balanced(self):
        ds = self._build()
        weights = ds["class_weights"]
        train = [r for r in ds["rows"] if r["split"] == "train"]
        total = len(train)
        for cls in rd.CLASSES:
            n_cls = sum(1 for r in train if r["label"] == cls)
            if n_cls:
                self.assertAlmostEqual(
                    weights[cls], total / (3 * n_cls))

    def test_ledger_phase05_parsing(self):
        ledger = (
            "| 2 | 144331452 | 94.6 | 1.08 | 2.87 | "
            "KILLED — persistence MIXED | phase-0.5 brightening "
            "−2.85% @ −157σ; shape unmeasured |\n"
        )
        (self.dir / "LEDGER2.md").write_text(ledger)
        parsed = rd.parse_ledger(str(self.dir / "LEDGER2.md"))
        self.assertEqual(parsed["144331452"]["rank"], 2)
        self.assertAlmostEqual(
            parsed["144331452"]["phase05_sigma"], -157.0)


if __name__ == "__main__":
    unittest.main()
