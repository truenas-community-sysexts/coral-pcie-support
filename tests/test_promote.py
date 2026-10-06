"""Run promote.yml's github-script under node with a stub GitHub client.

Each test closes a hardware-test issue against a canned release list and
checks the release update and issue comment the workflow would make: a
sign-off on any train (stable or preview) makes a full release and adds the
verified-train marker in the same update, Latest goes to the newest
signed-off build by build order, and a second close changes nothing."""
import copy
import json
import re
import subprocess
import unittest
from pathlib import Path

from release_fixtures import issue, marker, release
from test_promote_ranking import ranking_snippet
from test_release_selection import train_key
from workflow_script import run_script, step_script

ROOT = Path(__file__).resolve().parents[1]
PROMOTE_YML = ROOT / ".github" / "workflows" / "promote.yml"
BUILD_YML = ROOT / ".github" / "workflows" / "build.yml"

HARNESS = """
const state = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = { updates: [], comments: [], generated: [], compared: [] };
console.log = (...a) => process.stderr.write(a.join(' ') + '\\n');
const notFound = () => Object.assign(new Error('Not Found'), { status: 404 });
const github = {
  paginate: async (fn, args) => (await fn(args)).data,
  rest: {
    repos: {
      getReleaseByTag: async ({ tag }) => {
        const r = state.releases.find((x) => x.tag_name === tag);
        if (!r) throw notFound();
        return { data: r };
      },
      listReleases: async () => ({ data: state.releases }),
      generateReleaseNotes: async (args) => {
        out.generated.push(args);
        return { data: { body: "## What's Changed\\n* fix: a change by @someone" } };
      },
      compareCommitsWithBasehead: async (args) => {
        out.compared.push(args.basehead);
        return { data: { commits: [{ sha: 'abcdef1234567', commit: { message: 'fix: a change\\n\\nmore' } }] } };
      },
      updateRelease: async (args) => { out.updates.push(args); },
    },
    issues: { createComment: async (args) => { out.comments.push(args.body); } },
  },
};
const context = { repo: { owner: 'truenas-community-sysexts', repo: 'coral-pcie-support' },
                  payload: { issue: state.issue } };
const core = { info: () => {}, warning: () => {} };
(async () => {
%s
})().then(() => process.stdout.write(JSON.stringify(out)),
          (e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
"""


def promote_script():
    return step_script("promote.yml", "Record the sign-off on the release this issue gates")


def close(iss, releases):
    return run_script(HARNESS, promote_script(), {"issue": iss, "releases": releases})


def apply(releases, update):
    """The release list after the workflow's updateRelease call."""
    rels = copy.deepcopy(releases)
    for r in rels:
        if r["id"] == update["release_id"]:
            r["prerelease"] = update.get("prerelease", r["prerelease"])
            r["body"] = update.get("body", r["body"])
    return rels


K33 = "6.12.33-production+truenas"
K91 = "6.12.91-production+truenas"
K105 = "6.12.105-production+truenas"
K42 = "6.18.42-production+truenas"

R14 = "k6.12.105-gasket1.0-18.4-r14"
R15 = "k6.18.42-gasket1.0-18.4-r15"
R3 = "v25.10.4-gasket1.0-18.4-r3"
R7 = "v25.10.3-gasket1.0-18.4-r7"


def stable_rels():
    return [release(R14, "25.10.7", kver=K105, prerelease=True,
                    published="2026-09-19T18:22:44Z"),
            release(R7, "25.10.3", kver=K33, published="2026-06-26T03:47:02Z"),
            release(R3, "25.10.4", kver=K91, published="2026-06-08T22:36:46Z")]


def preview_rels():
    return [release(R15, "26.0.0-BETA.3", "Halfmoon", kver=K42, prerelease=True,
                    published="2026-09-19T18:24:06Z")] + stable_rels()


STABLE_ISSUE = dict(labels=("hardware-test",), preview=False)
PREVIEW_ISSUE = dict(labels=("preview-hardware-test",), preview=True)


class StableSignOff(unittest.TestCase):
    def test_promotes_and_adds_the_marker_in_one_update(self):
        rels = stable_rels()
        out = close(issue(R14, **STABLE_ISSUE), rels)
        self.assertEqual(len(out["updates"]), 1, out)
        up = out["updates"][0]
        self.assertIs(up["prerelease"], False)
        self.assertEqual(up["make_latest"], "true")  # newest kernel wins
        self.assertTrue(up["body"].startswith(rels[0]["body"]))
        self.assertEqual(up["body"].count("## Changelog"), 1)
        self.assertEqual(up["body"].count(marker("25.10")), 1)
        self.assertTrue(up["body"].rstrip().endswith(marker("25.10")))
        self.assertIn("promoted", out["comments"][0])
        self.assertIn("approved for TrueNAS train `25.10`", out["comments"][0])

    def test_latest_follows_build_order(self):
        # Promoting an older build (lower run) does not take Latest from a
        # newer signed-off build, whatever kernel or train either targets.
        rels = [release("k6.12.33-gasket1.0-18.4-r2", "25.10.3.1", kver=K33,
                        prerelease=True, published="2026-09-20T00:00:00Z"),
                release(R3, "25.10.4", kver=K91, published="2026-06-08T22:36:46Z")]
        out = close(issue("k6.12.33-gasket1.0-18.4-r2", **STABLE_ISSUE), rels)
        up = out["updates"][0]
        self.assertEqual(up["make_latest"], "false")
        self.assertIn(marker("25.10"), up["body"])
        self.assertIn(f"Latest stays on the newer `{R3}`", out["comments"][0])

    def test_legacy_issue_without_preview_marker_takes_the_same_path(self):
        rels = stable_rels()
        out = close(issue(R14), rels)
        self.assertIs(out["updates"][0]["prerelease"], False)
        self.assertIn(marker("25.10"), out["updates"][0]["body"])

    def test_grandfathered_full_release_is_left_alone(self):
        # Already approved for every train; a marker would narrow that.
        out = close(issue(R3, **STABLE_ISSUE), stable_rels())
        self.assertEqual(out["updates"], [])
        self.assertIn("already promoted", out["comments"][0])

    def test_full_release_approved_for_another_train_gets_this_one(self):
        rels = [release("k6.18.60-gasket1.0-18.4-r30", "26.0.0", "Halfmoon",
                        kver="6.18.60-production+truenas",
                        verified=["27"])]
        out = close(issue("k6.18.60-gasket1.0-18.4-r30", **STABLE_ISSUE), rels)
        up = out["updates"][0]
        self.assertNotIn("prerelease", up)
        self.assertEqual(up["make_latest"], "false")
        self.assertEqual(up["body"], rels[0]["body"] + f"\n\n{marker('26')}\n")

    def test_changelog_starts_at_the_previous_promoted_release(self):
        rels = stable_rels()
        out = close(issue(R14, **STABLE_ISSUE), rels)
        self.assertEqual(out["compared"], [f"{R7}...{R14}"])


class PreviewSignOff(unittest.TestCase):
    def test_promotes_like_a_stable_build(self):
        rels = preview_rels()
        out = close(issue(R15, **PREVIEW_ISSUE), rels)
        self.assertEqual(len(out["updates"]), 1, out)
        up = out["updates"][0]
        self.assertIs(up["prerelease"], False)
        self.assertEqual(up["make_latest"], "true")  # newest build (r15)
        self.assertTrue(up["body"].startswith(rels[0]["body"]))
        self.assertEqual(up["body"].count("## Changelog"), 1)
        self.assertTrue(up["body"].rstrip().endswith(marker("26")))
        self.assertIn("promoted", out["comments"][0])
        self.assertIn("approved for TrueNAS train `26`", out["comments"][0])

    def test_every_preview_signal_gives_the_preview_train(self):
        # Mislabeled as a stable test, a preview build is still approved for
        # its own (preview) train only, taken from the notes header.
        rels = preview_rels()
        for iss in (issue(R15, labels=("hardware-test",), preview=True),
                    issue(R15, labels=("hardware-test",))):
            out = close(iss, rels)
            self.assertIs(out["updates"][0]["prerelease"], False, iss)
            self.assertIn(marker("26"), out["updates"][0]["body"])
            self.assertNotIn(marker("25.10"), out["updates"][0]["body"])

    def test_changelog_starts_at_the_previous_preview_release(self):
        # The previous full release of the same channel, not a stable build
        # that may come from the same commit.
        older = "k6.18.42-gasket1.0-18.4-r13"
        rels = preview_rels() + [release(older, "26.0.0-BETA.3", "Halfmoon",
                                         kver=K42, verified=["26"],
                                         published="2026-09-19T10:00:00Z")]
        out = close(issue(R15, **PREVIEW_ISSUE), rels)
        self.assertEqual(out["compared"], [f"{older}...{R15}"])

    def test_full_preview_release_without_a_marker_gets_one(self):
        # No train installs a full preview build without a marker, so it is
        # not grandfathered: the sign-off adds its train.
        rels = [release(R15, "26.0.0-BETA.3", "Halfmoon", kver=K42,
                        prerelease=False, published="2026-09-19T18:24:06Z")]
        out = close(issue(R15, **PREVIEW_ISSUE), rels)
        up = out["updates"][0]
        self.assertNotIn("prerelease", up)
        self.assertEqual(up["make_latest"], "false")
        self.assertEqual(up["body"], rels[0]["body"] + f"\n\n{marker('26')}\n")

    def test_selection_takes_it_on_its_train_only(self):
        from test_release_selection import run_selection
        rels = preview_rels()
        p = run_selection(rels, "26.0.0-BETA.3", K42)
        self.assertNotEqual(p.returncode, 0)
        out = close(issue(R15, **PREVIEW_ISSUE), rels)
        rels = apply(rels, out["updates"][0])
        p = run_selection(rels, "26.0.0-BETA.3", K42)
        self.assertEqual(p.stdout, R15)
        # A full release now, but a 25.10 box still never installs it, and
        # a 27 box does not either (another train).
        p = run_selection(rels, "25.10.7", K105)
        self.assertNotEqual(p.returncode, 0)
        p = run_selection(rels, "27.0.0-RC.1", K42)
        self.assertNotEqual(p.returncode, 0)


class Idempotent(unittest.TestCase):
    def test_second_close_changes_nothing(self):
        for rels, iss, train in ((preview_rels(), issue(R15, **PREVIEW_ISSUE), "26"),
                                 (stable_rels(), issue(R14, **STABLE_ISSUE), "25.10")):
            first = close(iss, rels)
            rels = apply(rels, first["updates"][0])
            again = close(dict(iss, number=2), rels)
            self.assertEqual(again["updates"], [], train)
            self.assertIn(f"already approved for TrueNAS train `{train}`",
                          again["comments"][0])
            body = next(r for r in rels if r["tag_name"] == iss["body"].split()[1])["body"]
            self.assertEqual(body.count(marker(train)), 1)


class Guards(unittest.TestCase):
    def test_issue_without_release_tag_changes_nothing(self):
        iss = dict(issue(R14), body="no markers here")
        out = close(iss, stable_rels())
        self.assertEqual(out, {"updates": [], "comments": [], "generated": [],
                               "compared": []})

    def test_missing_release_is_reported(self):
        out = close(issue("k6.12.200-gasket1.0-18.4-r99"), stable_rels())
        self.assertEqual(out["updates"], [])
        self.assertIn("No release found for tag", out["comments"][0])

    def test_train_comes_from_a_legacy_v_tag_when_the_body_has_no_header(self):
        tag = "v25.10.5-gasket1.0-18.4-r8"
        rels = [dict(release(tag, "25.10.5", kver="6.12.95-production+truenas",
                             prerelease=True), body="")]
        out = close(issue(tag), rels)
        self.assertIn(marker("25.10"), out["updates"][0]["body"])

    def test_no_version_anywhere_changes_nothing(self):
        tag = "k6.12.95-gasket1.0-18.4-r8"
        rels = [dict(release(tag, prerelease=True), body="")]
        out = close(issue(tag), rels)
        self.assertEqual(out["updates"], [])
        self.assertIn("Cannot tell which TrueNAS train", out["comments"][0])


class Trigger(unittest.TestCase):
    def test_job_runs_for_both_labels_on_completed_only(self):
        text = PROMOTE_YML.read_text()
        cond = text[text.index("    if: >-"):text.index("    runs-on:")]
        self.assertIn("'hardware-test'", cond)
        self.assertIn("'preview-hardware-test'", cond)
        self.assertIn("github.event.issue.state_reason == 'completed'", cond)


TRAIN_DRIVER = """
const versions = JSON.parse(require('fs').readFileSync(0, 'utf8'));
console.log(JSON.stringify(versions.map((v) => trainKey(v))));
"""

VERSIONS = ["25.10.7", "25.10.3.1", "25.04.2.6", "25.10-RC.1", "26.0.0-BETA.3",
            "26.0.0-RC.1", "26.1.2", "26", "27.0.0-BETA.1", "", "abc", "25",
            "25.", "x25.10", "025.10.1"]


def js_train_keys(prefix_source):
    p = subprocess.run(["node", "-e", prefix_source + TRAIN_DRIVER],
                       input=json.dumps(VERSIONS), capture_output=True, text=True)
    if p.returncode != 0:
        raise AssertionError(p.stderr)
    return json.loads(p.stdout)


def train_key_source(path):
    text = path.read_text()
    start = text.index("const trainKey = (v) => {")
    end = text.index("};", start) + 2
    return text[start:end]


class TrainKeyParity(unittest.TestCase):
    """promote.yml's trainKey, build.yml's copy and install.sh's
    truenas_train_key give the same key for every version."""

    def test_promote_train_key_matches_the_installers(self):
        got = js_train_keys(ranking_snippet())
        want = [train_key(v) or "" for v in VERSIONS]
        self.assertEqual(got, want)

    def test_build_yml_has_the_same_train_key(self):
        norm = lambda s: re.sub(r"\s+", " ", s)
        self.assertEqual(norm(train_key_source(BUILD_YML)),
                         norm(train_key_source(PROMOTE_YML)))


if __name__ == "__main__":
    unittest.main()
