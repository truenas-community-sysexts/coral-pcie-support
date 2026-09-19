"""Render the hardware-test issue build.yml opens and check its procedure.

The github-script body of the "Create hardware-test issue" step is extracted
verbatim and run under node with a stub GitHub client, exactly the code the
workflow executes. The issue is a procedure a human follows by hand, so these
checks pin what its commands depend on: the markers promote.yml parses,
install.sh flags that exist, and release assets the release step uploads."""
import json
import os
import re
import subprocess
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_YML = ROOT / ".github" / "workflows" / "build.yml"
INSTALL_SH = ROOT / "scripts" / "install.sh"

STEP_NAME = "- name: Create hardware-test issue for auto-build"


def issue_script():
    lines = BUILD_YML.read_text().splitlines()
    step = next(i for i, ln in enumerate(lines) if ln.strip() == STEP_NAME)
    start = next(i for i in range(step, len(lines))
                 if lines[i].strip() == "script: |")
    indent = len(lines[start]) - len(lines[start].lstrip())
    block = []
    for ln in lines[start + 1:]:
        if ln.strip() and len(ln) - len(ln.lstrip()) <= indent:
            break
        block.append(ln)
    return textwrap.dedent("\n".join(block))


HARNESS = """
const captured = [];
console.log = (...a) => process.stderr.write(a.join(' ') + '\\n');
const github = { rest: { issues: {
  createLabel: async () => ({}),
  listForRepo: async () => ({ data: JSON.parse(process.env.OPEN_TITLES || '[]')
    .map((title) => ({ title })) }),
  create: async (args) => { captured.push(args); },
} } };
const context = { repo: { owner: 'truenas-community-sysexts', repo: 'coral-pcie-support' } };
(async () => {
%s
})().then(() => process.stdout.write(JSON.stringify(captured[0] ?? null)),
          (e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
"""


def render_issue(version, kver, run="50", driver="1.0-18.4", preview=False,
                 short_kver=None, open_titles=()):
    """The issues.create() arguments, or None when the step skips creating
    one because an issue in open_titles already names the tag."""
    env = dict(os.environ, TRUENAS_VERSION=version, GASKET_DRIVER=driver,
               RUN_NUMBER=run, REAL_KVER=kver,
               SHORT_KVER=kver.split("-")[0] if short_kver is None else short_kver,
               IS_PREVIEW="true" if preview else "false",
               OPEN_TITLES=json.dumps(list(open_titles)))
    p = subprocess.run(["node", "-e", HARNESS % issue_script()],
                       capture_output=True, text=True, env=env)
    if p.returncode != 0:
        raise AssertionError(f"node failed: {p.stderr}")
    return json.loads(p.stdout)


def code_lines(body):
    """Lines inside fenced code blocks."""
    out, inside = [], False
    for ln in body.splitlines():
        if ln.startswith("```"):
            inside = not inside
            continue
        if inside:
            out.append(ln)
    return out


def installer_flags():
    text = INSTALL_SH.read_text()
    return set(re.findall(r"^\s+(--[a-z-]+=?)\*?\)", text, re.MULTILINE))


def released_assets():
    text = BUILD_YML.read_text()
    block = text[text.index("body_path: release-notes.md"):]
    block = block[block.index("files: |"):block.index("draft: true")]
    return {Path(ln.strip()).name for ln in block.splitlines()[1:]
            if ln.strip() and not ln.strip().startswith("#")}


K105 = "6.12.105-production+truenas"
K42 = "6.18.42-production+truenas"


class Markers(unittest.TestCase):
    # promote.yml reads these; see its release-tag and preview-build regexes.
    def test_stable_markers(self):
        issue = render_issue("25.10.7", K105, run="11")
        tag = "k6.12.105-gasket1.0-18.4-r11"
        lines = issue["body"].splitlines()
        self.assertIn(f"<!-- release-tag: {tag} -->", lines)
        self.assertIn("<!-- preview-build: false -->", lines)
        m = re.search(r"<!--\s*release-tag:\s*(\S+?)\s*-->", issue["body"])
        self.assertEqual(m.group(1), tag)
        self.assertIn(tag, issue["title"])
        self.assertEqual(issue["labels"], ["hardware-test"])

    def test_preview_markers(self):
        issue = render_issue("26.0.0-BETA.3", K42, run="10", preview=True)
        self.assertIn("<!-- preview-build: true -->", issue["body"].splitlines())
        self.assertEqual(issue["labels"], ["preview-hardware-test"])


class Title(unittest.TestCase):
    # What to test | on what | which build. The step skips creating an issue
    # when an open one's title includes the tag, so the tag must appear in
    # the title verbatim; it goes last.
    STABLE_TAG = "k6.12.105-gasket1.0-18.4-r14"
    PREVIEW_TAG = "k6.18.42-gasket1.0-18.4-r15"

    def test_stable_title(self):
        issue = render_issue("25.10.7", K105, run="14")
        self.assertEqual(issue["title"],
                         "Hardware test: Coral TPU driver Gasket 1.0-18.4 | "
                         "TrueNAS 25.10.7 (kernel 6.12.105) | "
                         f"{self.STABLE_TAG}")

    def test_preview_title(self):
        issue = render_issue("26.0.0-BETA.3", K42, run="15", preview=True)
        self.assertEqual(issue["title"],
                         "Preview hardware test: Coral TPU driver Gasket 1.0-18.4 | "
                         "TrueNAS 26.0.0-BETA.3 (kernel 6.18.42) | "
                         f"{self.PREVIEW_TAG}")

    def test_unknown_kernel_is_left_out(self):
        for preview, prefix in ((False, "Hardware test"),
                                (True, "Preview hardware test")):
            issue = render_issue("25.10.7", "", run="14", preview=preview,
                                 short_kver="6.12.105")
            self.assertEqual(issue["title"],
                             f"{prefix}: Coral TPU driver Gasket 1.0-18.4 | "
                             f"TrueNAS 25.10.7 | {self.STABLE_TAG}")

    def test_title_ends_with_the_tag(self):
        for version, kver, run, preview, tag in (
                ("25.10.7", K105, "14", False, self.STABLE_TAG),
                ("26.0.0-BETA.3", K42, "15", True, self.PREVIEW_TAG)):
            title = render_issue(version, kver, run=run, preview=preview)["title"]
            self.assertIn(tag, title)
            self.assertTrue(title.endswith(f" | {tag}"), title)

    def test_open_issue_with_this_title_blocks_a_duplicate(self):
        # The step's own title must satisfy its duplicate check.
        for version, kver, run, preview in (
                ("25.10.7", K105, "14", False),
                ("26.0.0-BETA.3", K42, "15", True)):
            title = render_issue(version, kver, run=run, preview=preview)["title"]
            self.assertIsNone(render_issue(version, kver, run=run, preview=preview,
                                           open_titles=[title]))


class Procedure(unittest.TestCase):
    def setUp(self):
        self.stable = render_issue("25.10.7", K105, run="11")["body"]
        self.preview = render_issue("26.0.0-BETA.3", K42, run="10",
                                    preview=True)["body"]

    def test_kernel_requirement_is_the_real_kernel(self):
        self.assertIn(f"# must print exactly: {K105}", self.stable)
        self.assertIn(f"prints exactly `{K42}`", self.preview)

    def test_installer_is_never_run_from_a_pipe_or_missing_path(self):
        # A piped install.sh leaves no ./install.sh behind, and a
        # piped installer cannot find coral-lib.sh beside itself.
        for body in (self.stable, self.preview):
            self.assertNotIn("./install.sh", body)
            self.assertNotIn("| sudo bash", body)
            runs = [ln for ln in code_lines(body) if "install.sh" in ln
                    and not ln.startswith("curl ")]
            self.assertTrue(runs)
            for ln in runs:
                self.assertTrue(ln.startswith("sudo bash install.sh"), ln)

    def test_every_installer_flag_exists(self):
        flags = installer_flags()
        for body in (self.stable, self.preview):
            used = set(re.findall(r"install\.sh[^\n#]*?(--[a-z-]+=?)", body))
            used |= set(re.findall(r"`(--[a-z-]+=?)[A-Z]*`", body))
            self.assertTrue(used)
            self.assertLessEqual(used, flags)

    def test_quoted_installer_output_exists(self):
        # Expected-result comments quote install.sh's own output; a reworded
        # message would leave the tester looking for text that never prints.
        text = INSTALL_SH.read_text()
        for body in (self.stable, self.preview):
            runs = [ln for ln in code_lines(body)
                    if ln.startswith("sudo bash install.sh") and "#" in ln]
            quoted = [q for ln in runs
                      for q in re.findall(r'"([^"]+)"', ln.split("#", 1)[1])]
            self.assertTrue(quoted)
            for q in quoted:
                self.assertIn(q, text)

    def test_every_download_is_a_release_asset(self):
        assets = released_assets()
        for body in (self.stable, self.preview):
            names = re.findall(r"^curl -fsSL -o (\S+) (\S+)$",
                               "\n".join(code_lines(body)), re.MULTILINE)
            self.assertTrue(names)
            for out, url in names:
                self.assertEqual(url.rsplit("/", 1)[1], out)
                self.assertIn(out, assets)
            got = {out for out, _ in names}
            self.assertLessEqual({"coral.raw", "coral.raw.sha256",
                                  "install.sh", "coral-lib.sh"}, got)

    def test_step_3_explains_the_upgrade_preinit_fail(self):
        # Installing over a build for another kernel: the previous boot's
        # PREINIT mismatch error shows as 1 fail until the step 4 reboot.
        # The quoted texts must be what install.sh and coral-preinit.sh print.
        for body in (self.stable, self.preview):
            step3 = body[body.index("### 3. Verify"):
                         body.index("### 4. Reboot and re-verify")]
            self.assertIn("Upgrading over an earlier build for a different "
                          "kernel", step3)
            self.assertIn("`--check` here also shows 1 fail, `PREINIT logged "
                          "an error this boot` with a `Kernel version "
                          "mismatch` message", step3)
            self.assertIn("clears after the reboot in step 4, where 0 fail "
                          "is required", step3)
        self.assertIn("PREINIT logged an error this boot",
                      INSTALL_SH.read_text())
        self.assertIn("Kernel version mismatch",
                      (ROOT / "scripts" / "coral-preinit.sh").read_text())

    def test_step_2_explains_the_same_kernel_insmod_skip(self):
        # Reinstalling on the running kernel with the modules loaded:
        # install.sh skips insmod for each one (it would fail with File
        # exists). The skip lines quoted must be what install.sh prints.
        text = INSTALL_SH.read_text()
        for body in (self.stable, self.preview):
            step2 = body[body.index("### 2. Install this build"):
                         body.index("### 3. Verify")]
            self.assertIn("Reinstalling on the same kernel while the Coral "
                          "modules are loaded", step2)
            self.assertIn("this build's modules load at the reboot in "
                          "step 4", step2)
            self.assertNotIn("WARNING: insmod", step2)
            quoted = re.findall(r"`((gasket|apex) already loaded, "
                                r"skipping insmod[^`]*)`", step2)
            self.assertEqual([m for _, m in quoted], ["gasket", "apex"], step2)
            for q, _ in quoted:
                self.assertIn(q, text)

    def test_sign_off_semantics(self):
        self.assertIn("**Close as completed** promotes", self.stable)
        self.assertIn("**Close as not planned** rejects it", self.stable)
        self.assertNotIn("promotes [", self.preview)
        self.assertIn("never promoted to Latest", self.preview)



class TrainApproval(unittest.TestCase):
    # promote.yml approves the build for the train of the TrueNAS version in
    # its notes header, which is this issue's TRUENAS_VERSION; the issue
    # tells the tester which train that is.

    def test_stable_issue_names_its_train(self):
        body = render_issue("25.10.7", K105, run="14")["body"]
        self.assertIn("approves it for TrueNAS train `25.10`", body)
        self.assertIn(f"boxes whose kernel is `{K105}`", body)

    def test_preview_issue_names_its_train_and_does_not_promote(self):
        body = render_issue("26.0.0-BETA.3", K42, run="15", preview=True)["body"]
        self.assertIn("**Close as completed** approves [`k6.18.42-gasket1.0-18.4-r15`]",
                      body)
        self.assertIn("for TrueNAS train `26`", body)
        self.assertIn("Until this test signs it off for TrueNAS train `26`, "
                      "installs never receive it.", body)
        self.assertIn("**Close as not planned** rejects it", body)


class NoUntestedPublish(unittest.TestCase):
    # A full release with no verified-train marker counts as approved for
    # every train, so no build may be published as one.

    def test_build_yml_has_no_mark_latest(self):
        self.assertNotIn("mark_latest", BUILD_YML.read_text())
        self.assertNotIn("MARK_LATEST", BUILD_YML.read_text())

    def test_every_build_publishes_as_a_prerelease(self):
        text = BUILD_YML.read_text()
        step = text[text.index("- name: Publish the draft"):
                    text.index("- name: Create hardware-test issue")]
        self.assertIn("PUBLISH_ARGS=(-F draft=false -F prerelease=true)", step)
        self.assertNotIn("make_latest=true", step)
        self.assertEqual(step.count("PUBLISH_ARGS=("), 1)

    def test_every_build_gets_its_hardware_test_issue(self):
        text = BUILD_YML.read_text()
        step = text[text.index(STEP_NAME):]
        step = step[:step.index("with:")]
        self.assertNotIn("if:", step)

    def test_check_releases_dispatches_only_inputs_build_yml_takes(self):
        # A workflow_dispatch with an input the workflow does not declare is
        # rejected (HTTP 422), so a dropped input must leave every caller.
        text = BUILD_YML.read_text()
        dispatch = text[text.index("workflow_dispatch:"):text.index("workflow_call:")]
        declared = set(re.findall(r"^      (\w+):$", dispatch, re.MULTILINE))
        check = (ROOT / ".github" / "workflows" / "check-releases.yml").read_text()
        blocks = re.findall(r"inputs: \{(.*?)\}", check, re.S)
        self.assertEqual(len(blocks), 2)
        for block in blocks:
            used = set(re.findall(r"^\s+(\w+):", block, re.MULTILINE))
            self.assertTrue(used)
            self.assertLessEqual(used, declared)
        self.assertNotIn("mark_latest", check)


if __name__ == "__main__":
    unittest.main()
