"""Offline unit tests for .github/scripts/gen-supported-versions.py."""
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "gen-supported-versions.py"
spec = importlib.util.spec_from_file_location("gen_supported_versions", SCRIPT)
gsv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gsv)


def release(tag, version, train, kver, prerelease=False,
            published="2026-01-01T00:00:00Z"):
    body = (f"## Coral PCIe TPU Sysext for TrueNAS SCALE {version} ({train})\n"
            "| Field | Value |\n| --- | --- |\n"
            "| Gasket driver | `1.0-18.4` |\n")
    if kver:
        body += f"| Target kernel | `{kver}` |\n"
    return {"tag_name": tag, "body": body, "prerelease": prerelease,
            "draft": False, "html_url": f"https://example.test/{tag}",
            "published_at": published}


KERNEL_MAP = {"trains": {"Goldeye": {
    "25.10.0": "6.12.33-production+truenas",
    "25.10.1": "6.12.33-production+truenas",
    "25.10.2": "6.12.33-production+truenas",
    "25.10.3": "6.12.33-production+truenas",
    "25.10.3.1": "6.12.33-production+truenas",
    "25.10.4": "6.12.91-production+truenas",
}}}


def rows_for(releases, kernel_map=KERNEL_MAP):
    stable, preview = gsv.served_releases(gsv.parse_releases(releases))
    return gsv.build_rows(stable, preview, kernel_map)


class KernelRows(unittest.TestCase):
    def test_release_covers_whole_kernel_range(self):
        rows = rows_for([release("v25.10.3-gasket1.0-18.4-r39", "25.10.3",
                                 "Goldeye", "6.12.33-production+truenas")])
        row = [r for r in rows if r["kver"] == "6.12.33-production+truenas"][0]
        self.assertEqual(row["versions"], "25.10.0 - 25.10.3.1")
        self.assertEqual(row["tag"], "v25.10.3-gasket1.0-18.4-r39")
        self.assertEqual(row["driver"], "Gasket 1.0-18.4")

    def test_unbuilt_kernel_gets_row(self):
        rows = rows_for([])
        row = [r for r in rows if r["kver"] == "6.12.91-production+truenas"][0]
        self.assertEqual(row["tag"], "")
        self.assertEqual(row["versions"], "25.10.4")

    def test_unpromoted_stable_build_not_served(self):
        rows = rows_for([release("v25.10.4-gasket1.0-18.4-r40", "25.10.4",
                                 "Goldeye", "6.12.91-production+truenas",
                                 prerelease=True)])
        row = [r for r in rows if r["kver"] == "6.12.91-production+truenas"][0]
        self.assertEqual(row["tag"], "")

    def test_newest_kernel_row_first(self):
        rows = rows_for([])
        self.assertEqual(rows[0]["kver"], "6.12.91-production+truenas")

    def test_preview_release_row(self):
        rows = rows_for([release("v26.0.0-BETA.2-gasket1.0-18.4-r38",
                                 "26.0.0-BETA.2", "Halfmoon",
                                 "6.18.23-production+truenas", prerelease=True)])
        pr = [r for r in rows if r["channel"] == "Preview (beta)"]
        self.assertEqual(len(pr), 1)
        self.assertEqual(pr[0]["versions"], "26.0.0-BETA.2")
        self.assertEqual(pr[0]["tag"], "v26.0.0-BETA.2-gasket1.0-18.4-r38")

    def test_release_outside_map_keeps_own_row(self):
        rows = rows_for([release("v25.04.1-gasket1.0-18.2-r5", "25.04.1",
                                 "Fangtooth", "6.12.15-production+truenas")])
        own = [r for r in rows if r["versions"] == "25.04.1"]
        self.assertEqual(len(own), 1)

    def test_empty_map_still_lists_releases(self):
        rows = rows_for([release("v25.10.3-gasket1.0-18.4-r39", "25.10.3",
                                 "Goldeye", "6.12.33-production+truenas")],
                        kernel_map={})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["versions"], "25.10.3")


class RenderTable(unittest.TestCase):
    def test_not_built_yet_cell(self):
        lines = gsv.render_table(rows_for([]))
        self.assertTrue(any("_not built yet_" in line for line in lines))

    def test_version_range_helper(self):
        self.assertEqual(gsv.version_range(["25.10.0"]), "25.10.0")
        self.assertEqual(gsv.version_range(["25.10.3.1", "25.10.0", "25.10.2"]),
                         "25.10.0 - 25.10.3.1")


if __name__ == "__main__":
    unittest.main()
