"""Contract tests across the sign-off path, end to end.

build.yml renders the release notes and opens the hardware-test issue;
closing it runs promote.yml; the installer then selects by the notes
promote.yml leaves behind. Each piece is the real code (notes template,
issue script, promote script, selection snippet), so a change to any one
format that the next one no longer reads breaks CI here."""
import re
import unittest

from release_fixtures import marker
from test_hardware_test_issue import render_issue
from test_notes_header_contract import rendered_release
from test_promote import apply, close
from test_release_selection import run_selection

K105 = "6.12.105-production+truenas"
K42 = "6.18.42-production+truenas"


def built(version, train_name, kver, run, preview):
    """The release build.yml publishes (a prerelease) and the issue it
    opens for it."""
    rel = rendered_release(version, train_name, kver, prerelease=True)
    iss = render_issue(version, kver, run=str(run), preview=preview)
    tag = re.search(r"<!--\s*release-tag:\s*(\S+?)\s*-->", iss["body"]).group(1)
    rel = dict(rel, tag_name=tag, id=run)
    iss = dict(iss, number=run, labels=[{"name": n} for n in iss["labels"]])
    return rel, iss


class SignOffPath(unittest.TestCase):
    def test_stable_build_installs_on_its_train_only_after_sign_off(self):
        rel, iss = built("25.10.7", "Goldeye", K105, 50, preview=False)
        rels = [rel]
        self.assertNotEqual(run_selection(rels, "25.10.7", K105).returncode, 0)
        out = close(iss, rels)
        rels = apply(rels, out["updates"][0])
        self.assertIn(marker("25.10"), rels[0]["body"])
        self.assertFalse(rels[0]["prerelease"])
        p = run_selection(rels, "25.10.8", K105)
        self.assertEqual(p.stdout, rel["tag_name"], p.stderr)
        self.assertNotEqual(run_selection(rels, "26.0.1", K105).returncode, 0)

    def test_preview_build_installs_on_its_train_only_after_sign_off(self):
        rel, iss = built("26.0.0-BETA.3", "Halfmoon", K42, 51, preview=True)
        rels = [rel]
        self.assertNotEqual(run_selection(rels, "26.0.0-BETA.3", K42).returncode, 0)
        out = close(iss, rels)
        rels = apply(rels, out["updates"][0])
        self.assertTrue(rels[0]["prerelease"])
        self.assertIn(marker("26"), rels[0]["body"])
        p = run_selection(rels, "26.0.0-BETA.4", K42)
        self.assertEqual(p.stdout, rel["tag_name"], p.stderr)
        # The channel gate still keeps it off a stable box.
        self.assertNotEqual(run_selection(rels, "26.0.0", K42).returncode, 0)

    def test_issue_names_the_train_promote_writes(self):
        for version, name, kver, preview, train in (
                ("25.10.7", "Goldeye", K105, False, "25.10"),
                ("26.0.0-BETA.3", "Halfmoon", K42, True, "26")):
            rel, iss = built(version, name, kver, 52, preview)
            self.assertIn(f"TrueNAS train `{train}`", iss["body"])
            out = close(iss, [rel])
            self.assertTrue(out["updates"][0]["body"].rstrip()
                            .endswith(marker(train)))

    def test_fixture_marker_is_the_form_promote_writes(self):
        rel, iss = built("26.0.0-BETA.3", "Halfmoon", K42, 53, preview=True)
        out = close(iss, [rel])
        self.assertEqual(out["updates"][0]["body"],
                         rel["body"] + f"\n\n{marker('26')}\n")


if __name__ == "__main__":
    unittest.main()
