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
  listForRepo: async () => ({ data: [] }),
  create: async (args) => { captured.push(args); },
} } };
const context = { repo: { owner: 'truenas-community-sysexts', repo: 'coral-pcie-support' } };
(async () => {
%s
})().then(() => process.stdout.write(JSON.stringify(captured[0])),
          (e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
"""


def render_issue(version, kver, run="50", driver="1.0-18.4", preview=False):
    env = dict(os.environ, TRUENAS_VERSION=version, GASKET_DRIVER=driver,
               RUN_NUMBER=run, SHORT_KVER=kver.split("-")[0], REAL_KVER=kver,
               IS_PREVIEW="true" if preview else "false")
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


if __name__ == "__main__":
    unittest.main()
