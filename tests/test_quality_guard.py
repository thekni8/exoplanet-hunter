"""DF-2 guard test: no raw quality == 0 / != 0 split in production code.

The M-8 class of bug — splitting clean/flagged cadences on a
literal (q == 0)/(q != 0) — misclassified genuine bit-12
transits as flagged artifacts (TOI-700 c). The mask-consistent
split is (q & mask) == 0 / != 0. This test scans every
production Python file (token-based, so comments and
docstrings do not trip it) and fails on any raw split.

Allowlist entries are (file, line) pairs with a reason; each
is a DIAGNOSTIC measuring an any-flag fraction, not a
clean/flagged split. If an allowlisted line moves, the test
fails loudly so a human re-verifies the entry — that is the
point of a guard.

KNOWN_UNMASKED lists production files that deliberately do NO
quality filtering at all (DF-3 finding). It is documentation,
not a scan exemption: a raw split appearing in one of these
files still fails the test.
"""

import re
import tokenize
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

EXCLUDED_DIRS = {"tests", "archive", "__pycache__", ".git", ".venv"}

# (relative path, line number) -> (expected marker on that line, reason)
ALLOWLIST = {
    ("bulk/flag_fraction_sweep.py", 159): (
        "actual_frac",
        "Diagnostic: measures the achieved any-flag fraction of a "
        "synthetic FITS file, not a clean/flagged split.",
    ),
    ("bulk/inject_real_s96.py", 127): (
        "frac_any_flag",
        "Diagnostic: records the any-flag fraction of the substrate "
        "in the injection report, not a clean/flagged split.",
    ),
    ("bulk/inject_deep_real_s96.py", 123): (
        "frac_any_flag",
        "Diagnostic: records the any-flag fraction of the substrate "
        "in the injection report, not a clean/flagged split.",
    ),
}

# Files verified (DF-3) to do no quality filtering at all, with
# the evidence. Listed explicitly, never silently exempted.
KNOWN_UNMASKED = {
    "gauntlet/tesscut_fetch.py": (
        "Downloads TESSCut FFI cutouts (SPOC-style 16-bit QUALITY; "
        "bits 29/30 cannot occur) and uses unfiltered medians only "
        "for WCS identity; photometric use goes through the M-8 "
        "masked load_tpf. Verified DF-3."
    ),
}

# Raw-split patterns, on code tokens only (comments/strings
# stripped by the tokenizer). Covers q and quality, both
# comparison orders.
_SPLIT_RE = re.compile(
    r"\b(?:q|quality)\s*(?:==|!=)\s*0\b"
    r"|\b0\s*(?:==|!=)\s*(?:q|quality)\b"
)


def _code_lines(path):
    """Yield (line_no, code_text) with comments and string
    literals removed, via the tokenizer."""
    with open(path, encoding="utf-8") as fh:
        tokens = list(
            tokenize.generate_tokens(fh.readline)
        )
    by_line = {}
    for tok in tokens:
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        if tok.type in (tokenize.NL, tokenize.NEWLINE,
                        tokenize.INDENT, tokenize.DEDENT,
                        tokenize.ENCODING, tokenize.ENDMARKER):
            continue
        by_line.setdefault(tok.start[0], []).append(tok.string)
    for lineno in sorted(by_line):
        yield lineno, " ".join(by_line[lineno])


def _production_py_files():
    for path in sorted(REPO_ROOT.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        yield rel, path


class TestQualityGuard(unittest.TestCase):
    def test_no_raw_quality_split(self):
        violations = []
        found_allowlist = set()
        for rel, path in _production_py_files():
            # Raw lines for the marker check and the report: the
            # token-stripped code drops string literals, so a
            # dict-key marker like "frac_any_flag" is not in it.
            raw_lines = path.read_text(encoding="utf-8").splitlines()
            for lineno, code in _code_lines(path):
                if not _SPLIT_RE.search(code):
                    continue
                key = (str(rel), lineno)
                entry = ALLOWLIST.get(key)
                if entry is not None:
                    marker, _reason = entry
                    self.assertIn(
                        marker, raw_lines[lineno - 1],
                        f"Allowlisted line moved: {rel}:{lineno} "
                        f"no longer contains {marker!r} — re-verify "
                        "the entry before re-allowing it.",
                    )
                    found_allowlist.add(key)
                    continue
                violations.append(
                    f"{rel}:{lineno}: {raw_lines[lineno - 1].strip()}"
                )
        self.assertEqual(
            violations, [],
            "Raw quality == 0 / != 0 split(s) in production code "
            "(use (q & mask) == 0 / != 0 instead):\n"
            + "\n".join(violations),
        )
        stale = set(ALLOWLIST) - found_allowlist
        self.assertEqual(
            stale, set(),
            "Allowlist entries no longer match the tree (line moved "
            "or code removed) — re-verify and update:\n"
            + "\n".join(f"{p}:{n}" for p, n in sorted(stale)),
        )

    def test_known_unmasked_list_is_current(self):
        # Every KNOWN_UNMASKED entry must still exist in the tree,
        # so a deleted or renamed file fails loudly instead of
        # leaving a stale exemption behind.
        missing = [
            rel for rel in KNOWN_UNMASKED
            if not (REPO_ROOT / rel).is_file()
        ]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
