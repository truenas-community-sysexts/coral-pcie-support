"""Contract tests: every parser of the release-notes header against the
header build.yml actually renders.

install.sh (stable-channel preview lock), check-kernel-coverage.py,
promote.yml and gen-supported-versions.py all read the TrueNAS version out
of the notes header ("for TrueNAS SCALE <version> (<train>)"). A k-tag
carries no BETA/RC marker, so for kernel-tagged releases that header is the
only preview signal: rewording it would silently disable the preview locks.
These tests render the notes template straight out of build.yml (the same
envsubst substitution the workflow runs) and feed the result to each
parser, so a rewording breaks CI instead."""
import json
import re
import subprocess
import textwrap
import unittest
from pathlib import Path

from release_fixtures import release
from test_gen_supported_versions import gsv
from test_kernel_coverage import run_coverage
from test_promote_ranking import decide, ranking_snippet
from test_release_selection import run_selection

BUILD_YML = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "build.yml"

K33 = "6.12.33-production+truenas"
K99 = "6.12.99-production+truenas"


def notes_template():
    """The RELEASE_NOTES heredoc build.yml pipes through envsubst."""
    lines = BUILD_YML.read_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if "<<'RELEASE_NOTES'" in ln)
    end = next(i for i in range(start + 1, len(lines))
               if lines[i].strip() == "RELEASE_NOTES")
    return textwrap.dedent("\n".join(lines[start + 1:end]))


def header_template():
    """The notes header: the template's first markdown heading, located by
    structure rather than by the wording under test."""
    return next(ln for ln in notes_template().splitlines()
                if ln.startswith("## "))


def render_notes(version, train, kver):
    values = {
        "TRUENAS_VERSION": version, "TRAIN_NAME": train,
        "GASKET_DRIVER": "1.0-18.4", "GASKET_REF": "1.0-18.4",
        "GASKET_REPO": "feranick/gasket-driver", "REAL_KVER": kver,
        "RUNNER_IMAGE": "ubuntu-24.04", "BUILD_SHA": "0" * 40,
        "REPO": "truenas-community-sysexts/coral-pcie-support",
        "RUN_NUMBER": "50", "SHORT_KVER": kver.split("-")[0],
    }
    return re.sub(r"\$\{(\w+)\}",
                  lambda m: values.get(m.group(1), m.group(0)),
                  notes_template())


def rendered_release(version, train, kver, prerelease=False):
    """A k-tagged release (no BETA marker in the tag) whose body is exactly
    what build.yml publishes."""
    tag = f"k{kver.split('-')[0]}-gasket1.0-18.4-r50"
    return dict(release(tag, prerelease=prerelease),
                body=render_notes(version, train, kver))


class HeaderTemplate(unittest.TestCase):
    def test_header_names_the_truenas_version_and_train(self):
        hdr = header_template()
        self.assertIn("${TRUENAS_VERSION}", hdr)
        self.assertIn("${TRAIN_NAME}", hdr)

    def test_rendered_header_is_the_first_heading(self):
        body = render_notes("26.0.0-BETA.1", "Halfmoon", K99)
        first = next(ln for ln in body.splitlines() if ln.startswith("## "))
        self.assertIn("26.0.0-BETA.1", first)
        self.assertIn("Halfmoon", first)

    def test_shared_fixture_header_matches_build_yml(self):
        # The other suites build bodies with release_fixtures; keep its
        # header identical to the rendered one so they test the real format.
        body = render_notes("25.10.9", "Goldeye", K99)
        first = next(ln for ln in body.splitlines() if ln.startswith("## "))
        fixture = release("v25.10.9-gasket1.0-18.4-r1", "25.10.9", "Goldeye")
        self.assertEqual(fixture["body"].splitlines()[0], first)


class InstallerContract(unittest.TestCase):
    def test_stable_header_is_served_to_stable_box(self):
        rel = rendered_release("25.10.9", "Goldeye", K99)
        p = run_selection([rel], "25.10.9", K99)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, rel["tag_name"])

    def test_preview_header_is_refused_on_stable_box(self):
        # Mispublished without the prerelease flag, with a k-tag: the header
        # is the only thing marking it as a preview build.
        rel = rendered_release("26.0.0-BETA.1", "Halfmoon", K99)
        p = run_selection([rel], "25.10.9", K99)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("No stable release found", p.stderr)


class CoverageContract(unittest.TestCase):
    def test_stable_header_counts_as_coverage(self):
        rel = rendered_release("25.10.9", "Goldeye", K99)
        self.assertEqual(run_coverage([rel], kver=K99),
                         f"promoted {rel['tag_name']}")

    def test_preview_header_never_counts_as_coverage(self):
        rel = rendered_release("26.0.0-BETA.1", "Halfmoon", K99)
        self.assertEqual(run_coverage([rel], kver=K99), "")


PROMOTE_DRIVER = """
const r = JSON.parse(require('fs').readFileSync(0, 'utf8'));
console.log(JSON.stringify({ ver: bodyVerOf(r), preview: previewRelease(r) }));
"""


def promote_parse(rel):
    p = subprocess.run(["node", "-e", ranking_snippet() + PROMOTE_DRIVER],
                       input=json.dumps(rel), capture_output=True, text=True)
    if p.returncode != 0:
        raise AssertionError(f"node failed: {p.stderr}")
    return json.loads(p.stdout)


class PromoteContract(unittest.TestCase):
    # bodyVerOf feeds both promote.yml's refusal to promote a k-tagged
    # preview build and the Latest comparison set.

    def test_stable_header_version_is_read(self):
        res = promote_parse(rendered_release("25.10.9", "Goldeye", K99))
        self.assertEqual(res, {"ver": "25.10.9", "preview": False})

    def test_preview_header_version_is_read(self):
        res = promote_parse(rendered_release("26.0.0-BETA.1", "Halfmoon", K99))
        self.assertEqual(res, {"ver": "26.0.0-BETA.1", "preview": True})

    def test_mispublished_preview_cannot_hold_latest(self):
        res = decide(release("v25.10.3-gasket1.0-18.4-r7", "25.10.3", kver=K33),
                     [rendered_release("26.0.0-BETA.1", "Halfmoon", K99)])
        self.assertEqual(res["makeLatest"], "true")


class SupportedVersionsContract(unittest.TestCase):
    def test_header_yields_version_train_and_kernel(self):
        parsed = gsv.parse_releases([
            rendered_release("25.10.9", "Goldeye", K99),
            rendered_release("26.0.0-BETA.1", "Halfmoon", K33,
                             prerelease=True),
        ])
        self.assertEqual(sorted(parsed), ["25.10.9", "26.0.0-BETA.1"])
        stable = parsed["25.10.9"][0]
        self.assertEqual((stable["train"], stable["kver"], stable["driver"]),
                         ("Goldeye", K99, "Gasket 1.0-18.4"))
        self.assertEqual(parsed["26.0.0-BETA.1"][0]["train"], "Halfmoon")


if __name__ == "__main__":
    unittest.main()
