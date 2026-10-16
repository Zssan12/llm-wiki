"""End-to-end runs of bin/ingest.py against a fake `claude` CLI (tests/fake-engine/claude)."""
import json, sqlite3, time, unittest

from helpers import TempWiki, git

DEMO = [("user", "The staging server is reachable as demo-staging over SSH, port 2222."),
        ("assistant", "Noted: demo-staging, SSH port 2222."),
        ("user", "Always run the linter before committing.")]


class IngestTest(unittest.TestCase):
    def setUp(self):
        self.w = TempWiki()
        self.addCleanup(self.w.cleanup)
        self.sid = self.w.session(DEMO)
        self.sid8 = self.sid[:8]

    def db(self, table):
        con = sqlite3.connect(self.w.wiki / ".ingest.sqlite")
        try:
            return dict(con.execute(f"select id, offset from {table}"))
        finally:
            con.close()

    def size(self):
        return (self.w.transcripts / "-home-demo-project" / f"{self.sid}.jsonl").stat().st_size

    def test_session_ingest_is_accepted_and_delivered(self):
        r = self.w.ingest("--session", self.sid)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"ingest {self.sid8}", self.w.commits())
        page = (self.w.wiki / "misc" / "demo-facts.md").read_text()
        self.assertIn("demo-staging", page)
        self.assertIn(f"ingest | {self.sid8} Demo session", (self.w.wiki / "log.md").read_text())
        self.assertEqual(self.w.lint().returncode, 0)
        self.assertEqual(git(self.w.wiki, "status", "--porcelain"), "")  # delivered as a commit, tree clean
        self.assertEqual(self.db("ingested")[self.sid], self.size())
        self.assertNotIn("REVERTED", self.w.log_text())
        self.assertEqual(self.w.calls_made(), ["haiku INGEST"])
        # nothing new: a second run makes no model call
        self.w.ingest("--pending")
        self.assertEqual(self.w.calls_made(), ["haiku INGEST"])

    def test_touching_schema_is_rejected(self):
        self.w.ingest("--session", self.sid, mode="touch-schema")
        self.assertEqual(self.w.commits(), ["skeleton"])
        self.assertIn("R9: touched files outside the wiki pages: CLAUDE.md", self.w.log_text())
        self.assertFalse((self.w.wiki / "misc" / "demo-facts.md").exists())
        self.assertNotIn(self.sid, self.db("ingested"))
        con = sqlite3.connect(self.w.wiki / ".ingest.sqlite")
        self.assertEqual(con.execute("select n from fails where id=?", (self.sid,)).fetchone()[0], 1)
        con.close()

    def test_missing_log_entry_is_rejected(self):
        self.w.ingest("--session", self.sid, mode="no-log")
        self.assertEqual(self.w.commits(), ["skeleton"])
        self.assertIn(f"A2: no new log.md entry", self.w.log_text())

    def test_fallback_engine_redoes_failed_batch(self):
        self.w.ingest("--session", self.sid, mode="fail-haiku")
        self.assertEqual(self.w.calls_made(), ["haiku INGEST", "sonnet INGEST"])
        self.assertIn(f"ingest {self.sid8}", self.w.commits())

    def test_nightly_reviews_and_dreams(self):
        self.w.ingest("--session", self.sid)
        r = self.w.ingest("--nightly")
        self.assertEqual(r.returncode, 0, r.stderr)
        commits = self.w.commits()
        self.assertIn(f"review {self.sid8}", commits)
        self.assertIn("dream 1 sessions", commits)
        cand = (self.w.wiki / "misc" / "rule-candidates.md").read_text()
        self.assertIn(self.sid8, cand)
        self.assertEqual(self.db("reviewed")[self.sid], self.size())
        self.assertEqual(self.w.lint().returncode, 0)

    def test_dream_misquote_is_rejected(self):
        self.w.ingest("--session", self.sid)
        self.w.ingest("--nightly", mode="dream-misquote")
        self.assertNotIn("dream 1 sessions", self.w.commits())
        self.assertIn("quotes not found among the USER lines", self.w.log_text())

    def test_weekly_lint_runs(self):
        r = self.w.ingest("--lint")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("sonnet LINT", self.w.calls_made())

    def test_hook_runs_session_in_background(self):
        r = self.w.ingest("--hook", stdin=json.dumps({"session_id": self.sid}))
        self.assertEqual(r.returncode, 0, r.stderr)
        deadline = time.time() + 60
        while time.time() < deadline and f"ingest {self.sid8}" not in self.w.commits():
            time.sleep(0.5)
        self.assertIn(f"ingest {self.sid8}", self.w.commits())

    def test_status_lists_pending(self):
        r = self.w.ingest("--status")
        self.assertIn(self.sid, r.stdout)


class ConfigTest(unittest.TestCase):
    def test_unknown_key_is_refused(self):
        w = TempWiki(config={"no_such_key": 1})
        self.addCleanup(w.cleanup)
        r = w.ingest("--status")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unknown key(s) no_such_key", r.stderr)


if __name__ == "__main__":
    unittest.main()
