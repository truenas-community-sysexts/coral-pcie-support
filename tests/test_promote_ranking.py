"""Unit tests for the Latest-ranking logic embedded in promote.yml.

The JavaScript between the BEGIN/END promote-ranking sentinels is extracted
verbatim (dedented from its YAML indentation) and run under node with a
canned release list, exactly the code the workflow executes."""
import json
import subprocess
import unittest
from pathlib import Path

from release_fixtures import release

PROMOTE_YML = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "promote.yml"


def ranking_snippet():
    text = PROMOTE_YML.read_text()
    begin_mark = "// BEGIN promote-ranking"
    begin = text.rindex("\n", 0, text.index(begin_mark)) + 1
    end = text.index("// END promote-ranking")
    indent = text.index(begin_mark) - begin
    block = text[begin:end]
    return "\n".join(line[indent:] for line in block.splitlines())


DRIVER = """
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const res = decideMakeLatest(input.release, input.others);
console.log(JSON.stringify(res));
"""


def decide(rel, others):
    p = subprocess.run(["node", "-e", ranking_snippet() + DRIVER],
                       input=json.dumps({"release": rel, "others": others}),
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise AssertionError(f"node failed: {p.stderr}")
    return json.loads(p.stdout)


K33 = "6.12.33-production+truenas"
K91 = "6.12.91-production+truenas"
K105 = "6.12.105-production+truenas"
K42 = "6.18.42-production+truenas"
K52 = "6.18.52-production+truenas"


class BuildOrder(unittest.TestCase):
    # Latest is the newest signed-off build on any train, by build order
    # (the -r<N> run number), so a late sign-off never moves it backwards.

    def test_newer_build_takes_latest(self):
        res = decide(release("k6.12.105-gasket1.0-18.4-r14", "25.10.7", kver=K105),
                     [release("v25.10.4-gasket1.0-18.4-r3", "25.10.4", kver=K91)])
        self.assertEqual(res["makeLatest"], "true")

    def test_older_build_signed_off_late_does_not_take_latest(self):
        res = decide(release("v25.10.3-gasket1.0-18.4-r7", "25.10.3", kver=K33),
                     [release("k6.12.105-gasket1.0-18.4-r14", "25.10.7", kver=K105)])
        self.assertEqual(res["makeLatest"], "false")
        self.assertEqual(res["newest"], "k6.12.105-gasket1.0-18.4-r14")

    def test_run_number_decides_across_tag_schemes(self):
        res = decide(release("v25.10.7-gasket1.0-18.4-r11", "25.10.7", kver=K105),
                     [release("k6.12.91-gasket1.0-18.4-r9", "25.10.4", kver=K91)])
        self.assertEqual(res["makeLatest"], "true")

    def test_prerelease_others_cannot_hold_latest(self):
        res = decide(release("v25.10.3-gasket1.0-18.4-r7", "25.10.3", kver=K33),
                     [release("k6.12.105-gasket1.0-18.4-r14", "25.10.7", kver=K105,
                              prerelease=True)])
        self.assertEqual(res["makeLatest"], "true")

    def test_tags_without_a_run_fall_back_to_publication_date(self):
        res = decide(release("v25.04.1-gasket1.0-18.2", "25.04.1",
                             published="2026-02-01T00:00:00Z"),
                     [release("v25.04.0-gasket1.0-18.2", "25.04.0",
                              published="2026-01-01T00:00:00Z")])
        self.assertEqual(res["makeLatest"], "true")
        res = decide(release("v25.04.0-gasket1.0-18.2", "25.04.0",
                             published="2026-01-01T00:00:00Z"),
                     [release("v25.04.1-gasket1.0-18.2", "25.04.1",
                              published="2026-02-01T00:00:00Z")])
        self.assertEqual(res["makeLatest"], "false")


class AnyTrain(unittest.TestCase):
    # A preview sign-off is a release like any other: it can take Latest,
    # and it can hold it against a later sign-off of an older stable build.

    def test_newer_preview_build_takes_latest_from_stable(self):
        res = decide(release("k6.18.52-gasket1.0-18.4-r16", "27.0.0-RC.1",
                             "Halfmoon", kver=K52),
                     [release("v25.10.4-gasket1.0-18.4-r3", "25.10.4", kver=K91)])
        self.assertEqual(res["makeLatest"], "true")

    def test_older_stable_build_does_not_displace_newer_preview(self):
        res = decide(release("k6.12.105-gasket1.0-18.4-r14", "25.10.7", kver=K105),
                     [release("k6.18.52-gasket1.0-18.4-r16", "27.0.0-RC.1",
                              "Halfmoon", kver=K52, verified=["27"])])
        self.assertEqual(res["makeLatest"], "false")
        self.assertEqual(res["newest"], "k6.18.52-gasket1.0-18.4-r16")

    def test_newer_stable_build_takes_latest_from_older_preview(self):
        res = decide(release("k6.12.110-gasket1.0-18.4-r17", "25.10.8",
                             kver="6.12.110-production+truenas"),
                     [release("k6.18.52-gasket1.0-18.4-r16", "27.0.0-RC.1",
                              "Halfmoon", kver=K52, verified=["27"])])
        self.assertEqual(res["makeLatest"], "true")

    def test_unapproved_full_preview_cannot_hold_latest(self):
        # A preview build marked full by hand without a marker is approved
        # for no train (the installers do not grandfather previews).
        for tag, version in (("k6.18.52-gasket1.0-18.4-r16", "27.0.0-RC.1"),
                             ("v26.0.0-BETA.1-gasket1.0-18.4-r2", "26.0.0-BETA.1"),
                             ("k6.18.23-gasket1.0-18.4-r9", "26.0.0-RC1")):
            res = decide(release("v25.10.3-gasket1.0-18.4-r1", "25.10.3", kver=K33),
                         [release(tag, version, "Halfmoon", kver=K42)])
            self.assertEqual(res["makeLatest"], "true", tag)


if __name__ == "__main__":
    unittest.main()
