"""End-to-end runs of bin/ingest.py against a fake `claude` CLI (tests/fake-engine/claude)."""
import json, sqlite3, time, unittest
from pathlib import Path

from helpers import TempWiki, git

DEMO = [("user", "The staging server is reachable as demo-staging over SSH, port 2222."),
        ("assistant", "Noted: demo-staging, SSH port 2222."),
        ("user", "Always run the linter before committing.")]


class IngestZhTest(unittest.TestCase):
    """Runs the pipeline with language "zh": Chinese SOP prompts, Chinese page sections."""
    language, key_section, task_word = "zh", "## 关键事实", "任务"

    def setUp(self):
        self.w = TempWiki(config={"language": self.language})
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
        self.assertIn(self.key_section, page)
        self.assertIn(f"ingest | {self.sid8} Demo session", (self.w.wiki / "log.md").read_text())
        self.assertEqual(self.w.lint().returncode, 0)
        self.assertEqual(git(self.w.wiki, "status", "--porcelain"), "")  # delivered as a commit, tree clean
        self.assertEqual(self.db("ingested")[self.sid], self.size())
        self.assertNotIn("REVERTED", self.w.log_text())
        self.assertEqual(self.w.calls_made(), ["haiku INGEST"])
        prompt = (self.w.tmp / "calls.txt.prompts").read_text()
        self.assertTrue(prompt.startswith(f"INGEST {self.task_word}"), prompt)
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

    def test_nightly_writes_machine_readable_diff_report(self):
        self.w.ingest("--session", self.sid)
        r = self.w.ingest("--nightly")
        self.assertEqual(r.returncode, 0, r.stderr)
        report = json.loads((self.w.wiki / "state" / f"diff-{time.strftime('%Y-%m-%d')}.json").read_text())
        self.assertEqual(report["schema"], 1)
        self.assertGreaterEqual(report["summary"]["total"], 1)
        self.assertIn("review diff report", " ".join(self.w.commits()))

    def test_diff_engine_fixes_fabricated_attribution(self):
        self.w.ingest("--session", self.sid, mode="bad-write")
        r = self.w.ingest("--nightly", mode="bad-write")
        self.assertEqual(r.returncode, 0, r.stderr)
        page = (self.w.wiki / "misc" / "demo-facts.md").read_text()
        self.assertNotIn("用户定：", page)
        report = json.loads((self.w.wiki / "state" / f"diff-{time.strftime('%Y-%m-%d')}.json").read_text())
        bad = [c for c in report["changes"] if "用户定" in c["text"]]
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["verdict"], "misattributed")
        self.assertTrue(bad[0]["fixed"])
        self.assertGreaterEqual(report["summary"]["fixed"], 1)

    def test_proposals_cli_accept_and_reject(self):
        self.w.ingest("--session", self.sid)
        self.w.ingest("--nightly")
        records = json.loads((self.w.wiki / "misc" / "rule-candidates.json").read_text())["proposals"]
        self.assertTrue(records)
        listed = self.w.ingest("proposals", "list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn(records[0]["id"], listed.stdout)
        target = self.w.home / ".claude" / "CLAUDE.md"
        self.assertFalse(target.exists())
        accepted = self.w.ingest("proposals", "accept", records[0]["id"])
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertIn("resident rule file not modified", accepted.stdout)
        self.assertFalse(target.exists())  # accept only writes a patch
        self.assertEqual(json.loads((self.w.wiki / "misc" / "rule-candidates.json").read_text())["proposals"][0]["status"],
                         "accepted")
        second = records[1]["id"]
        rejected = self.w.ingest("proposals", "reject", second, "不适用")
        self.assertEqual(rejected.returncode, 0, rejected.stderr)
        word = "已否决" if self.language == "zh" else "Rejected"
        self.assertIn(word, (self.w.wiki / "misc" / "rule-candidates.md").read_text())

    def test_new_engines_can_be_disabled(self):
        w = TempWiki(config={"language": self.language, "diff_engine": False, "proposal_engine": False})
        self.addCleanup(w.cleanup)
        sid = w.session(DEMO)
        w.ingest("--session", sid)
        r = w.ingest("--nightly")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"review {sid[:8]}", w.commits())
        self.assertIn("dream 1 sessions", w.commits())
        self.assertFalse((w.wiki / "state" / f"diff-{time.strftime('%Y-%m-%d')}.json").exists())
        self.assertFalse((w.wiki / "misc" / "rule-candidates.json").exists())

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


class IngestEnTest(IngestZhTest):
    """Runs the pipeline with language "en": English SOP prompts, English page sections."""
    language, key_section, task_word = "en", "## Key facts", "task"


class RemoteTest(unittest.TestCase):
    def test_first_run_pushes_to_an_empty_remote(self):
        w = TempWiki(config={"remote": "origin"})
        self.addCleanup(w.cleanup)
        bare = w.tmp / "remote.git"
        git(w.tmp, "init", "-q", "--bare", str(bare))
        git(w.wiki, "remote", "add", "origin", str(bare))
        sid = w.session(DEMO)
        r = w.ingest("--session", sid)
        self.assertEqual(r.returncode, 0, r.stderr)
        head = git(w.wiki, "rev-parse", "HEAD")
        self.assertIn(head, git(w.tmp, "ls-remote", str(bare)))
        self.assertNotIn("FAILED", w.log_text())
        # second run: the branch now exists on the remote; pull and push again
        sid2 = w.session(DEMO)
        w.ingest("--session", sid2)
        self.assertIn(f"ingest {sid2[:8]}", w.commits())
        self.assertIn(git(w.wiki, "rev-parse", "HEAD"), git(w.tmp, "ls-remote", str(bare)))
        self.assertNotIn("FAILED", w.log_text())


class ConfigTest(unittest.TestCase):
    def test_unknown_language_is_refused(self):
        w = TempWiki(config={"language": "fr"})
        self.addCleanup(w.cleanup)
        r = w.ingest("--status")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("language must be", r.stderr)

    def test_unknown_key_is_refused(self):
        w = TempWiki(config={"no_such_key": 1})
        self.addCleanup(w.cleanup)
        r = w.ingest("--status")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unknown key(s) no_such_key", r.stderr)


if __name__ == "__main__":
    unittest.main()
