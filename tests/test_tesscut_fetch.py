"""Regression test for the tesscut_fetch sector typo (2026-11-15).

fetch_sector passed `sector=sectortor` to lightkurve's TESSCut search
— an undefined name, so every call raised NameError and the function
was unusable. No test covered fetch_sector directly, which is why the
typo survived on main. This test proves the search receives the
caller's sector, all offline (mocked search + passthrough mast_call).

On the pre-fix code this test fails with NameError: name
'sectortor' is not defined.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gauntlet import tesscut_fetch  # noqa: E402


class TestFetchSectorSearch(unittest.TestCase):
    def test_search_receives_caller_sector(self):
        calls = []

        def fake_search(target, sector=None):
            calls.append((target, sector))
            return []  # no cutouts: fetch_sector returns NO-DATA

        def passthrough(fn, **kwargs):
            return fn()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("lightkurve.search_tesscut",
                            side_effect=fake_search), \
                    mock.patch("netbound.mast_call",
                               side_effect=passthrough):
                tpf, reason = tesscut_fetch.fetch_sector(
                    423498314, 32, tmpdir)

        self.assertIsNone(tpf)
        self.assertEqual(reason, "no TESSCut cutout found")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "TIC 423498314")
        self.assertEqual(calls[0][1], 32)


if __name__ == "__main__":
    unittest.main()
