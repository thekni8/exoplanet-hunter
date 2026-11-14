"""Fingerprint-coverage test (Phase 1.2 follow-up F-9).

`fingerprint_result_affecting` hashes a GLOB-based file set
(*.py, gauntlet/*.py, bulk/*.py, calibration/*.yaml,
schema/*.json). A new top-level directory — or a pipeline module
that imports from outside the hashed dirs — would silently
escape it, and a code change there would not refuse a resume.
This test fails if any module the pipeline imports escapes the
hashed set.

Method: static import analysis (ast) over every .py file in
the hashed code dirs (root, gauntlet/, bulk/). Each import is
resolved against the repo (dotted names to paths; bare names
searched in root/, gauntlet/, bulk/ — the sys.path order the
code itself uses); third-party/stdlib imports resolve to
nothing and are skipped. Every resolved repo file must be in
the glob expansion. A negative control (temp tree) proves the
analysis actually reports an escape.
"""
import ast
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import provenance as prov  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# The entry points whose transitive imports must all be hashed.
# (They live in the hashed dirs by construction; this list pins
# the intent — the closure check below is the real test.)
ENTRY_POINTS = ("hunter.py", "bulk_screen.py",
                "bulk/run_chunked.py",
                "bulk/build_target_list.py",
                "bulk/build_ledger.py",
                "gauntlet/runner.py", "gauntlet/verdict.py",
                "gauntlet/stage_result.py",
                "gauntlet/rawflux_check.py",
                "gauntlet/transit_fit.py",
                "gauntlet/diffimg.py", "gauntlet/blend.py",
                "injection_harness.py", "sweep_runner.py",
                "api.py")


def _hashed_files(root):
    """The fingerprint's file set, from the same globs the
    fingerprint itself uses (not a copy — a glob change is
    tested, not duplicated)."""
    files = set()
    for pattern in prov._RESULT_AFFECTING_GLOBS:
        for path in sorted(Path(root).glob(pattern)):
            if path.is_file():
                files.add(path.relative_to(root).as_posix())
    return files


def _resolve_module(root, dotted):
    """Resolve a dotted module name to a repo-relative file, or
    None when it is not a repo module (stdlib/third-party).
    Bare names are searched in root/, gauntlet/, bulk/ — the
    sys.path order the code itself uses for its fallback
    imports (`from blend import ...` when run from gauntlet/)."""
    parts = dotted.split(".")
    search_bases = [Path(root)] if len(parts) > 1 else [
        Path(root), Path(root) / "gauntlet", Path(root) / "bulk"]
    for base in search_bases:
        cand = base.joinpath(*parts).with_suffix(".py")
        if cand.is_file():
            return cand.relative_to(root).as_posix()
        init = base.joinpath(*parts) / "__init__.py"
        if init.is_file():
            return init.relative_to(root).as_posix()
    return None


def _imports_of(path):
    """Dotted module names imported by one file (ast, whole
    file including function bodies — lazy imports count)."""
    tree = ast.parse(Path(path).read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
    return names


def find_escaping_imports(root):
    """{(importer, imported): resolved file} for every import
    from a hashed .py file that resolves to a repo file OUTSIDE
    the hashed set. Empty when coverage is complete."""
    root = Path(root)
    hashed = _hashed_files(root)
    code_files = sorted(p for p in hashed if p.endswith(".py"))
    escaping = {}
    for rel in code_files:
        for name in _imports_of(root / rel):
            resolved = _resolve_module(root, name)
            if resolved is not None and resolved not in hashed:
                escaping[(rel, name)] = resolved
    return escaping


class TestFingerprintCoverage(unittest.TestCase):
    def test_entry_points_are_hashed(self):
        hashed = _hashed_files(ROOT)
        for entry in ENTRY_POINTS:
            self.assertIn(entry, hashed,
                          msg=f"entry point {entry} is not in "
                              f"the hashed file set")

    def test_no_imported_module_escapes(self):
        escaping = find_escaping_imports(ROOT)
        self.assertEqual(
            escaping, {},
            msg="imported repo modules outside the hashed set: "
                + "; ".join(
                    f"{imp} imports {name} -> {resolved}"
                    for (imp, name), resolved
                    in sorted(escaping.items())))

    def test_analysis_reports_an_escape(self):
        # Negative control: a temp tree where a hashed module
        # imports from a directory outside the globs must be
        # reported — otherwise this test could never fail.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text(
                "from elsewhere.foo import bar\n")
            (root / "elsewhere").mkdir()
            (root / "elsewhere" / "foo.py").write_text("bar = 1\n")
            escaping = find_escaping_imports(root)
            self.assertEqual(
                escaping,
                {("a.py", "elsewhere.foo"): "elsewhere/foo.py"})


if __name__ == "__main__":
    unittest.main()
