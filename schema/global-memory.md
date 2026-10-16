# Memory = LLM wiki

The auto-memory directory is `~/wiki` (git), a layered LLM wiki. Before writing to it, read `~/wiki/CLAUDE.md` (the schema).
- Read top-down only as deep as needed: `MEMORY.md` (domains) → `<domain>/README.md` (topics) → `<domain>/<topic>.md` (facts). History and session ids are in `~/wiki/log.md`.
- To remember something, update the topic page whose `scope` fits (or create one per the schema), keep the README/MEMORY.md in sync, append to log.md, run `python3 ~/wiki/bin/lint.py`, and commit.
- Never write secrets; record where they live instead.
- Before reading a paper or an external project, `grep -r <arXiv id|owner/name> ~/wiki`; after a deep read, write it into `refs/` right away (format: "Reading notes" in ~/wiki/CLAUDE.md).
- `~/wiki/bin/ingest.py` distills sessions on close (SessionEnd hook) and every 30 minutes for idle ones; for details not in the wiki, open the original session (e.g. with a session-resume tool).
