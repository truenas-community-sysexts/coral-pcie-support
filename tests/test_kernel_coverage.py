"""Unit tests for .github/scripts/check-kernel-coverage.py.

The script decides whether check-releases.yml dispatches a build for a new
TrueNAS version's kernel. Its selection rules must stay in lockstep with
install.sh's release-selection snippet, so both test against the shared
release fixtures.
"""
import json
import subprocess
import unittest
from pathlib import Path

from release_fixtures import release

SCRIPT = (Path(__file__).resolve().parents[1]
          / ".github" / "scripts" / "check-kernel-coverage.py")

K93 = "6.12.93-production+truenas"
# A kernel-tagged Latest ships the kernel-aware installer, so coverage
# counts; the transition-guard tests below override it.
KTAG_LATEST = "k6.12.91-gasket1.0-18.4-r41"


def run_coverage_full(releases, kver=K93, driver="1.0-18.4", raw=None,
                      latest=KTAG_LATEST):
    text = raw if raw is not None else json.dumps(releases)
    env = {"NEW_KERNEL": kver, "CURRENT_DRIVER": driver,
           "PATH": "/usr/bin:/bin"}
    if latest is not None:
        env["LATEST_TAG"] = latest
    p = subprocess.run(["python3", str(SCRIPT)], input=text,
                       capture_output=True, text=True, env=env)
    if p.returncode != 0:
        raise AssertionError(f"script failed: {p.stderr}")
    return p


def run_coverage(releases, **kwargs):
    return run_coverage_full(releases, **kwargs).stdout.strip()


class Coverage(unittest.TestCase):
    def test_promoted_release_covers_its_body_kernel(self):
        out = run_coverage([release("v25.10.5-gasket1.0-18.4-r40", "25.10.5",
                                    kver=K93)])
        self.assertEqual(out, "promoted v25.10.5-gasket1.0-18.4-r40")

    def test_no_release_means_build(self):
        self.assertEqual(run_coverage([]), "")

    def test_other_kernel_means_build(self):
        out = run_coverage([release("v25.10.4-gasket1.0-18.4-r37", "25.10.4",
                                    kver="6.12.91-production+truenas")])
        self.assertEqual(out, "")

    def test_other_driver_means_build(self):
        out = run_coverage([release("v25.10.5-gasket1.0-18.4-r40", "25.10.5",
                                    kver=K93)], driver="1.0-19.0")
        self.assertEqual(out, "")

    def test_unpromoted_stable_build_is_pending_coverage(self):
        # An unpromoted build awaiting hardware test must not trigger a
        # duplicate build, but must be reported as pending so the tracked
        # version does not advance past it (a deleted build would otherwise
        # leave the kernel without a rebuild path).
        out = run_coverage([release("v25.10.5-gasket1.0-18.4-r40", "25.10.5",
                                    kver=K93, prerelease=True)])
        self.assertEqual(out, "pending v25.10.5-gasket1.0-18.4-r40")

    def test_promoted_release_preferred_over_pending(self):
        out = run_coverage([
            release("v25.10.5-gasket1.0-18.4-r41", "25.10.5", kver=K93,
                    prerelease=True),
            release("v25.10.5-gasket1.0-18.4-r40", "25.10.5", kver=K93),
        ])
        self.assertEqual(out, "promoted v25.10.5-gasket1.0-18.4-r40")

    def test_draft_never_covers(self):
        out = run_coverage([release("v25.10.5-gasket1.0-18.4-r40", "25.10.5",
                                    kver=K93, draft=True)])
        self.assertEqual(out, "")


class PreviewExclusion(unittest.TestCase):
    # Preview builds never promote, so install.sh's stable channel never
    # serves them: they provide no coverage (e.g. a GA release reusing the
    # last RC's kernel still needs its own stable build).

    def test_preview_tag_never_covers(self):
        out = run_coverage([release("v26.0.0-RC.1-gasket1.0-18.4-r44",
                                    "26.0.0-RC.1", kver=K93,
                                    prerelease=True)])
        self.assertEqual(out, "")

    def test_mispublished_preview_never_covers(self):
        out = run_coverage([release("v26.0.0-RC.1-gasket1.0-18.4-r44",
                                    "26.0.0-RC.1", kver=K93,
                                    prerelease=False)])
        self.assertEqual(out, "")

    def test_ktagged_preview_caught_by_body_header(self):
        out = run_coverage([release("k6.12.93-gasket1.0-18.4-r44",
                                    "26.0.0-RC.1", kver=K93,
                                    prerelease=True)])
        self.assertEqual(out, "")


class KtagFallback(unittest.TestCase):
    def test_promoted_ktag_with_lost_body_covers(self):
        rel = dict(release("k6.12.93-gasket1.0-18.4-r50"), body="")
        self.assertEqual(run_coverage([rel]),
                         "promoted k6.12.93-gasket1.0-18.4-r50")

    def test_unpromoted_ktag_with_lost_body_never_covers(self):
        # With the body gone there is no way to tell a stable build awaiting
        # promotion from a preview (BETA/RC) build, and counting a preview
        # as coverage would suppress the kernel's stable build forever. The
        # safe default is to build.
        rel = dict(release("k6.12.93-gasket1.0-18.4-r50", prerelease=True),
                   body="")
        self.assertEqual(run_coverage([rel]), "")

    def test_ktag_fallback_never_matches_other_short_kernel(self):
        rel = dict(release("k6.12.9-gasket1.0-18.4-r50"), body="")
        self.assertEqual(run_coverage([rel]), "")

    def test_body_row_overrides_ktag_on_mismatch(self):
        rel = release("k6.12.93-gasket1.0-18.4-r50", "25.10.3",
                      kver="6.12.33-production+truenas")
        self.assertEqual(run_coverage([rel]), "")


class LatestInstallerGuard(unittest.TestCase):
    # The README one-liner runs the install.sh attached to Latest. Only
    # k-tag builds ship the kernel-aware installer; a v-tag Latest matches
    # exact TrueNAS versions, so a skipped build would leave the new version
    # with "No stable release found". Coverage only counts under a k-tag
    # Latest, and every doubt resolves to "build".
    PROMOTED = [release("v25.10.5-gasket1.0-18.4-r40", "25.10.5", kver=K93)]
    PENDING = [release("v25.10.5-gasket1.0-18.4-r40", "25.10.5", kver=K93,
                       prerelease=True)]
    VTAG_LATEST = "v25.10.4-gasket1.0-18.4-r3"

    def test_ktag_latest_promoted_coverage_skips(self):
        self.assertEqual(run_coverage(self.PROMOTED, latest=KTAG_LATEST),
                         "promoted v25.10.5-gasket1.0-18.4-r40")

    def test_vtag_latest_promoted_coverage_builds(self):
        p = run_coverage_full(self.PROMOTED, latest=self.VTAG_LATEST)
        self.assertEqual(p.stdout.strip(), "")
        self.assertIn("predates the kernel-aware installer", p.stderr)

    def test_failed_latest_lookup_promoted_coverage_builds(self):
        p = run_coverage_full(self.PROMOTED, latest="")
        self.assertEqual(p.stdout.strip(), "")
        self.assertIn("lookup failed", p.stderr)

    def test_unset_latest_promoted_coverage_builds(self):
        self.assertEqual(run_coverage(self.PROMOTED, latest=None), "")

    def test_ktag_latest_pending_coverage_skips(self):
        self.assertEqual(run_coverage(self.PENDING, latest=KTAG_LATEST),
                         "pending v25.10.5-gasket1.0-18.4-r40")

    def test_vtag_latest_pending_coverage_builds(self):
        self.assertEqual(run_coverage(self.PENDING, latest=self.VTAG_LATEST),
                         "")

    def test_failed_latest_lookup_pending_coverage_builds(self):
        self.assertEqual(run_coverage(self.PENDING, latest=""), "")

    def test_ktag_covering_release_still_needs_ktag_latest(self):
        # The covering release's own tag scheme is irrelevant: what matters
        # is the installer the one-liner downloads, which comes from Latest.
        rel = [release("k6.12.93-gasket1.0-18.4-r50", "25.10.5", kver=K93)]
        self.assertEqual(run_coverage(rel, latest=self.VTAG_LATEST), "")

    def test_uncovered_kernel_prints_no_guard_note(self):
        p = run_coverage_full([], latest=self.VTAG_LATEST)
        self.assertEqual(p.stdout.strip(), "")
        self.assertEqual(p.stderr, "")


class Pagination(unittest.TestCase):
    def test_concatenated_pages_are_merged(self):
        page1 = [release("v25.10.4-gasket1.0-18.4-r37", "25.10.4",
                         kver="6.12.91-production+truenas")]
        page2 = [release("v25.10.5-gasket1.0-18.4-r40", "25.10.5", kver=K93)]
        raw = json.dumps(page1) + "\n" + json.dumps(page2) + "\n"
        self.assertEqual(run_coverage(None, raw=raw),
                         "promoted v25.10.5-gasket1.0-18.4-r40")


if __name__ == "__main__":
    unittest.main()
