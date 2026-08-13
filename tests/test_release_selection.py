"""Unit tests for the release-selection logic embedded in scripts/install.sh.

The Python between the BEGIN/END release-selection sentinels is extracted
verbatim and run as a subprocess with a canned GitHub releases JSON on
stdin, exactly how install.sh runs it."""
import json
import subprocess
import unittest
from pathlib import Path

INSTALL_SH = Path(__file__).resolve().parents[1] / "scripts" / "install.sh"


def selection_snippet():
    text = INSTALL_SH.read_text()
    begin = text.index("# BEGIN release-selection")
    end = text.index("# END release-selection")
    return text[begin:end]


def run_selection(releases, version, kver):
    return subprocess.run(
        ["python3", "-c", selection_snippet()],
        input=json.dumps(releases), capture_output=True, text=True,
        env={"VERSION": version, "KVER": kver, "PATH": "/usr/bin:/bin"})


def release(tag, kver=None, prerelease=False, draft=False,
            published="2026-01-01T00:00:00Z"):
    body = f"| Target kernel | `{kver}` |" if kver else "legacy body, no kernel row"
    return {"tag_name": tag, "body": body, "prerelease": prerelease,
            "draft": draft, "published_at": published}


RELEASES = [
    release("v25.10.3-gasket1.0-18.4-r39", "6.12.33-production+truenas"),
    release("v25.10.4-gasket1.0-18.4-r37", "6.12.91-production+truenas"),
    release("v25.10.5-gasket1.0-18.4-r40", "6.12.93-production+truenas",
            prerelease=True),
    release("v26.0.0-BETA.2-gasket1.0-18.4-r38", "6.18.23-production+truenas",
            prerelease=True),
    release("v25.04.1-gasket1.0-18.2-r5"),
]


class KernelMatch(unittest.TestCase):
    def test_unbuilt_point_release_matches_by_kernel(self):
        p = run_selection(RELEASES, "25.10.2", "6.12.33-production+truenas")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, "v25.10.3-gasket1.0-18.4-r39")

    def test_stable_box_never_gets_prerelease(self):
        p = run_selection(RELEASES, "25.10.5", "6.12.93-production+truenas")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("No stable release found", p.stderr)

    def test_preview_box_gets_prerelease(self):
        p = run_selection(RELEASES, "26.0.0-BETA.2", "6.18.23-production+truenas")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, "v26.0.0-BETA.2-gasket1.0-18.4-r38")

    def test_version_fallback_for_legacy_release(self):
        p = run_selection(RELEASES, "25.04.1", "6.12.15-production+truenas")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, "v25.04.1-gasket1.0-18.2-r5")
        self.assertIn("matched by TrueNAS version", p.stderr)

    def test_fallback_never_picks_wrong_advertised_kernel(self):
        # A release advertising a DIFFERENT kernel must not win on version
        # prefix: wrong modules cannot load.
        rels = [release("v25.10.9-gasket1.0-18.4-r50", "6.12.91-production+truenas")]
        p = run_selection(rels, "25.10.9", "6.12.99-production+truenas")
        self.assertNotEqual(p.returncode, 0)

    def test_no_match_lists_available_releases(self):
        p = run_selection(RELEASES, "25.10.9", "6.12.99-production+truenas")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("v25.10.4-gasket1.0-18.4-r37", p.stderr)
        self.assertIn("6.12.91-production+truenas", p.stderr)

    def test_draft_ignored(self):
        rels = RELEASES + [release("v25.10.9-gasket1.0-18.4-r99",
                                   "6.12.99-production+truenas", draft=True)]
        p = run_selection(rels, "25.10.9", "6.12.99-production+truenas")
        self.assertNotEqual(p.returncode, 0)


if __name__ == "__main__":
    unittest.main()
