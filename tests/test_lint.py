import unittest

from helpers import TempWiki

PAGE = """---
name: {name}
description: demo page
metadata:
  scope: demo facts
---
# Demo
## 现状
{body}
"""


class LintTest(unittest.TestCase):
    def setUp(self):
        self.w = TempWiki()
        self.addCleanup(self.w.cleanup)

    def add_page(self, name, body="- a fact", register=True, domain="misc"):
        (self.w.wiki / domain / f"{name}.md").write_text(PAGE.format(name=name, body=body))
        if register:
            with open(self.w.wiki / domain / "README.md", "a") as f:
                f.write(f"- [{name}]({name}.md) — demo page\n")

    def assertLint(self, ok, needle=""):
        r = self.w.lint()
        self.assertEqual(r.returncode, 0 if ok else 1, r.stdout)
        self.assertIn(needle, r.stdout)

    def test_skeleton_passes(self):
        self.assertLint(True, "lint ok")

    def test_valid_page_passes(self):
        self.add_page("demo")
        self.assertLint(True, "lint ok")

    def test_orphan_page(self):
        self.add_page("demo", register=False)
        self.assertLint(False, "orphan page")

    def test_unknown_section(self):
        self.add_page("demo", body="## Notes\n- x")
        self.assertLint(False, "section '## Notes'")

    def test_page_over_budget(self):
        self.add_page("demo", body="\n".join(f"- fact {i}" for i in range(80)))
        self.assertLint(False, "split into subtopics or compress")

    def test_long_line(self):
        self.add_page("demo", body="- " + "x" * 400)
        self.assertLint(False, "body line")

    def test_bookkeeping_phrase(self):
        self.add_page("demo", body="- 端口 8080（用户告知）")
        self.assertLint(False, "verification bookkeeping")

    def test_missing_frontmatter(self):
        (self.w.wiki / "misc" / "demo.md").write_text("# Demo\n- x\n")
        with open(self.w.wiki / "misc" / "README.md", "a") as f:
            f.write("- [demo](demo.md) — demo\n")
        self.assertLint(False, "frontmatter needs")

    def test_unlisted_domain(self):
        (self.w.wiki / "infra").mkdir()
        self.assertLint(False, "infra/: domain not listed in MEMORY.md")

    def test_stray_top_level_page(self):
        (self.w.wiki / "notes.md").write_text("x\n")
        self.assertLint(False, "top-level page")

    def test_memory_extra_line(self):
        with open(self.w.wiki / "MEMORY.md", "a") as f:
            f.write("some prose\n")
        self.assertLint(False, "only domain entry lines")

    def test_warn_near_budget_and_dangling_link(self):
        self.add_page("demo", body="\n".join(f"- fact {i} [[nowhere]]" for i in range(45)))
        r = self.w.lint("--warn")
        self.assertEqual(r.returncode, 0)
        self.assertIn("misc/demo.md: ", r.stdout)
        self.assertIn("[[nowhere]] has no page yet", r.stdout)


if __name__ == "__main__":
    unittest.main()
