"""Autouse calibration-restoration check for the deep pipeline
(deep_v2 vote, DF-6 — Claude's autouse teardown check).

Test classes that switch hunter's calibration inherit
DeepCalibrationGuardCase: after every test, a cleanup asserts
the active calibration is back to deep_v2 (version AND mask).
A leaked calibration — a switch whose restore never ran, e.g.
after an exception — fails the test that leaked it, loudly,
instead of silently contaminating the next test in the module.

The check is registered with addCleanup in setUp, so it runs
even when the test itself fails, and after tearDown (cleanups
run after tearDown, LIFO). Subclasses that define setUp MUST
call super().setUp() or the check never registers.

Scope: hunter (deep pipeline) only. The bulk screen's
calibration seam (bulk_screen.set_calibration) keeps its own
manual restore pattern — the bulk pipeline is out of scope
for this branch.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hunter  # noqa: E402
import quality_flags as qf  # noqa: E402


class DeepCalibrationGuardCase(unittest.TestCase):
    """Base class: asserts deep_v2 is restored after each test."""

    def setUp(self):
        super().setUp()
        self.addCleanup(self._assert_calibration_restored)

    def _assert_calibration_restored(self):
        # Both halves: a failed set_calibration assigns before
        # it validates, so version and mask can disagree.
        self.assertEqual(
            hunter.CALIBRATION_VERSION, "deep_v2",
            "hunter calibration leaked: a test switched away "
            "from deep_v2 and did not restore it (use "
            "hunter.calibration_context, which restores in a "
            "finally block)")
        self.assertEqual(
            hunter.QUALITY_MASK, qf.DEEP_V2_MASK,
            "hunter quality mask leaked: the version is deep_v2 "
            "but the mask is not the deep_v2 mask")
