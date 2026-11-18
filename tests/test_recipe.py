"""Unit tests for the recipe loader (bulk/recipe.py). No downloads.

Guards the config-driven-run contract: recipes load with the right
defaults, CLI overrides win, and malformed recipes are refused with a
clear error instead of silently screening the wrong star set.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bulk.recipe import (RecipeError, apply_overrides, load_recipe,  # noqa: E402
                         validate)

RECIPES = Path(__file__).resolve().parent.parent / "bulk" / "recipes"


class TestLoad(unittest.TestCase):
    def test_default_recipe(self):
        r = load_recipe(RECIPES / "default.yaml")
        self.assertIsNone(r["sector"])
        win = r["window"]
        self.assertEqual((win["min_mag"], win["max_mag"]), (10.0, 13.5))
        self.assertEqual((win["min_rad"], win["max_rad"]), (0.2, 0.8))
        self.assertTrue(win["require_radius"])
        self.assertIsNone(win["limit_ids"])
        self.assertEqual(r["tag"], "window_default")
        self.assertEqual(r["slice_size"], 1250)
        self.assertEqual(r["dl_workers"], 8)
        self.assertIsNone(r["workers"])
        self.assertIn("_file", r)

    def test_smoke_recipe(self):
        r = load_recipe(RECIPES / "smoke.yaml")
        self.assertEqual(r["sector"], 1)
        self.assertEqual(r["window"]["limit_ids"], 2000)
        self.assertEqual(r["slice_size"], 500)
        self.assertEqual(r["tag"], "window_smoke")

    def test_sector96_recipe_is_frozen_record(self):
        r = load_recipe(RECIPES / "sector-96.yaml")
        self.assertEqual(r["sector"], 96)
        self.assertEqual(r["tag"], "window_default")
        win = r["window"]
        self.assertEqual((win["min_mag"], win["max_mag"]), (10.0, 13.5))
        self.assertEqual((win["min_rad"], win["max_rad"]), (0.2, 0.8))

    def test_missing_file(self):
        with self.assertRaises(RecipeError):
            load_recipe(RECIPES / "no-such-recipe.yaml")


class TestOverrides(unittest.TestCase):
    def test_cli_wins_and_none_ignored(self):
        base = load_recipe(RECIPES / "default.yaml")
        # Overrides are FLAT (CLI-shaped); window keys nest on apply.
        out = apply_overrides(base, {"sector": 97, "min_mag": 11.0,
                                     "max_mag": None, "tag": "window_x"})
        self.assertEqual(out["sector"], 97)
        self.assertEqual(out["window"]["min_mag"], 11.0)
        self.assertEqual(out["window"]["max_mag"], 13.5)  # None: recipe
        self.assertEqual(out["tag"], "window_x")
        # The base dict is not mutated.
        self.assertIsNone(base["sector"])
        self.assertEqual(base["window"]["min_mag"], 10.0)

    def test_false_is_a_real_override(self):
        base = load_recipe(RECIPES / "default.yaml")
        out = apply_overrides(base, {"require_radius": False})
        self.assertFalse(out["window"]["require_radius"])

    def test_k3_defaults_off(self):
        # 4.1-1a: K=1 stays the default — the K=3 stage is opt-in
        # per recipe or CLI, never silently on.
        r = load_recipe(RECIPES / "default.yaml")
        self.assertIs(r["k3"], False)

    def test_k3_override(self):
        base = load_recipe(RECIPES / "default.yaml")
        r = apply_overrides(base, {"k3": True})
        self.assertIs(r["k3"], True)
        r2 = apply_overrides(r, {"k3": False})
        self.assertIs(r2["k3"], False)


class TestValidation(unittest.TestCase):
    def _bad(self, **kw):
        r = load_recipe(RECIPES / "default.yaml")
        r.update(kw)
        with self.assertRaises(RecipeError):
            validate(r)

    def _bad_window(self, **kw):
        r = load_recipe(RECIPES / "default.yaml")
        r["window"].update(kw)
        with self.assertRaises(RecipeError):
            validate(r)

    def test_bad_mag_range(self):
        self._bad_window(min_mag=13.5, max_mag=10.0)

    def test_bad_radius_range(self):
        self._bad_window(min_rad=0.8, max_rad=0.2)

    def test_unknown_key(self):
        self._bad(survivor_sde=7.0)  # thresholds live in bulk_screen.py

    def test_unknown_window_key(self):
        self._bad_window(survivor_sde=7.0)

    def test_bad_tag(self):
        self._bad(tag="../x")

    def test_bad_sector(self):
        self._bad(sector=0)

    def test_bad_slice_size(self):
        self._bad(slice_size=0)

    def test_bad_dl_workers(self):
        self._bad(dl_workers=0)

    def test_negative_limit(self):
        self._bad_window(limit_ids=-5)

    def test_bad_k3(self):
        self._bad(k3="yes")

    def test_unknown_override_key(self):
        base = load_recipe(RECIPES / "default.yaml")
        with self.assertRaises(RecipeError):
            apply_overrides(base, {"survivor_sde": 7.0})


if __name__ == "__main__":
    unittest.main()
