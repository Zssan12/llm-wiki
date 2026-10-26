#!/usr/bin/env python3
"""Proposal Engine: structured rule candidates behind ``misc/rule-candidates.md``.

A candidate is one record with a stable id, a normalized dedup key, the rule
draft, its target (a resident rule file + section, or a hook/test), every
occurrence (date, sid8, verbatim quote) and a status (``open`` / ``accepted`` /
``rejected``).  ``misc/rule-candidates.md`` is rendered from these records, so
the human page and the machine state cannot drift apart.

Rules from Issue #1:
- synonymous corrections merge on ``normalize_key``;
- a candidate is shown to the user only after ``MIN_OCCURRENCES`` occurrences;
- a rejected candidate is never proposed again;
- ``accept`` writes a patch under ``state/proposals/`` and never edits the
  resident rule file itself.

No model calls, no git commands: ``bin/ingest.py`` feeds this module and tests
exercise it directly.
"""
import difflib, hashlib, json, os, re, tempfile, time, unicodedata
from pathlib import Path

SCHEMA = 1
STATUSES = ("open", "accepted", "rejected")
# source: existing rule R5 and Issue #1 ("≥2 次进待办")
MIN_OCCURRENCES = 2
# source: lint.py BODY_LINE (300) minus the prefix/evidence budget; keeps generated lines valid.
DRAFT_CLIP = 120
PAGE = "misc/rule-candidates.md"
SCOPE = "rule candidates from dream, the user's accept/reject decisions, and proposal patches"


def normalize_key(text):
    """Normalized dedup key: NFKC, case-folded, punctuation and whitespace removed."""
    t = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"[\W_]+", "", t, flags=re.UNICODE)


def candidate_id(key):
    return "p-" + hashlib.sha1((key or "").encode("utf-8")).hexdigest()[:8]


def clip(text, limit=DRAFT_CLIP):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def normalize_target(target):
    """Accept a dict or a compact string (``file#section``, ``hook``, ``test``)."""
    if isinstance(target, dict):
        kind = str(target.get("kind") or "rule").lower()
        file = str(target.get("file") or "").strip()
        section = str(target.get("section") or "").strip()
    else:
        raw = str(target or "").strip()
        if raw.lower() in ("hook", "test"):
            kind, file, section = raw.lower(), "", ""
        elif "#" in raw:
            kind, (file, section) = "rule", raw.split("#", 1)
        else:
            kind, file, section = "rule", raw, ""
    if kind not in ("rule", "hook", "test"):
        kind = "rule"
    return {"kind": kind, "file": file or "~/.claude/CLAUDE.md", "section": section}


def target_label(target):
    target = normalize_target(target)
    if target["kind"] != "rule":
        return target["kind"]
    base = f"`{target['file']}`"
    return base + (f" › {target['section']}" if target["section"] else "")


def _occ(o):
    quote = str(o.get("quote") or "").strip()
    if quote.startswith("「") and quote.endswith("」"):
        quote = quote[1:-1]
    return {"date": str(o.get("date") or "").strip(),
            "sid8": str(o.get("sid8") or "").strip()[:8],
            "quote": quote}


def _unique_occurrences(items):
    out, seen = [], set()
    for o in items:
        o = _occ(o)
        k = (o["date"], o["sid8"], o["quote"])
        if o["sid8"] and o["quote"] and k not in seen:
            seen.add(k)
            out.append(o)
    return out


class ProposalStore:
    """JSON-backed candidate store.  One store per wiki, normally
    ``<wiki>/state/proposals.json`` (git-ignored runtime state)."""

    def __init__(self, path):
        self.path = Path(path)
        self.records = self._load()

    def _load(self):
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text())
        except ValueError:
            return []
        records = data.get("proposals", []) if isinstance(data, dict) else data
        out = []
        for r in records:
            if not isinstance(r, dict):
                continue
            r.setdefault("key", normalize_key(r.get("draft", "")))
            r.setdefault("id", candidate_id(r["key"]))
            r.setdefault("status", "open")
            r.setdefault("occurrences", [])
            r.setdefault("target", normalize_target(r.get("target")))
            r.setdefault("patch", "")
            r.setdefault("reason", "")
            r.setdefault("created", "")
            r.setdefault("updated", "")
            r["occurrences"] = _unique_occurrences(r["occurrences"])
            out.append(r)
        return out

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema": SCHEMA, "proposals": self.records}
        fd, tmp = tempfile.mkstemp(prefix=".proposals-", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w") as f:
                f.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def get(self, proposal_id):
        return next((r for r in self.records if r["id"] == proposal_id), None)

    def list(self, status=None):
        rows = [r for r in self.records if status is None or r["status"] == status]
        return sorted(rows, key=lambda r: (r["status"], r["id"]))

    def proposed(self, record):
        return record["status"] == "open" and len(record["occurrences"]) >= MIN_OCCURRENCES

    def add(self, draft, target=None, occurrences=(), key=None, today=None, save=True):
        """Add/merge one candidate.  Synonymous drafts share ``key``."""
        key = normalize_key(key or draft)
        if not key:
            raise ValueError("candidate needs a draft or key")
        today = today or time.strftime("%Y-%m-%d")
        existing = next((r for r in self.records if r["key"] == key), None)
        if existing:
            existing["occurrences"] = _unique_occurrences(list(existing["occurrences"]) + list(occurrences))
            existing["updated"] = today
            if draft and not existing.get("draft"):
                existing["draft"] = draft
            if target:
                existing["target"] = normalize_target(target)
            record = existing
        else:
            record = {"id": candidate_id(key), "key": key, "draft": str(draft or "").strip(),
                      "target": normalize_target(target), "occurrences": _unique_occurrences(list(occurrences)),
                      "status": "open", "patch": "", "reason": "",
                      "created": today, "updated": today}
            self.records.append(record)
        if save:
            self.save()
        return record

    def reject(self, proposal_id, reason="", today=None):
        record = self.get(proposal_id)
        if not record:
            raise KeyError(proposal_id)
        record["status"] = "rejected"
        record["reason"] = str(reason or "").strip()
        record["updated"] = today or time.strftime("%Y-%m-%d")
        self.save()
        return record

    def accept(self, proposal_id, patch_dir, patch_prefix="state/proposals", today=None):
        """Mark accepted and write a patch; never touch the target file."""
        record = self.get(proposal_id)
        if not record:
            raise KeyError(proposal_id)
        if record["status"] == "rejected":
            raise ValueError(f"{proposal_id} was rejected; reject is final")
        patch_dir = Path(patch_dir)
        patch_dir.mkdir(parents=True, exist_ok=True)
        target = normalize_target(record["target"])
        if target["kind"] == "rule":
            name = f"{proposal_id}.patch"
            content = rule_patch(target, record["draft"])
        else:
            name = f"{proposal_id}.proposal.md"
            content = (f"# Proposal {proposal_id} ({target['kind']})\n\n"
                       f"- rule draft: {record['draft']}\n"
                       f"- target: {target['kind']}\n"
                       f"- evidence: " + "; ".join(f"{o['date']} {o['sid8']}「{o['quote']}」"
                                                   for o in record["occurrences"]) + "\n\n"
                       "Generated by the Proposal Engine; nothing was applied.  A hook or test "
                       "needs a human-designed check before it can be added.\n")
        path = patch_dir / name
        path.write_text(content)
        record["status"] = "accepted"
        record["patch"] = f"{patch_prefix}/{name}"
        record["updated"] = today or time.strftime("%Y-%m-%d")
        self.save()
        return record, path


def insert_rule(text, section, draft, path="~/.claude/CLAUDE.md"):
    """Return new file text with ``- draft`` added under ``section`` (never writes)."""
    line = f"- {draft}".rstrip()
    if text and re.search(r"(?m)^" + re.escape(line) + r"\s*$", text):
        return text  # already present: an empty patch
    if not text:
        head = f"## {section}\n" if section else "## Rules\n"
        return f"# Rules\n\n{head}{line}\n"
    lines = text.splitlines()
    idx = None
    if section:
        for i, l in enumerate(lines):
            if re.match(r"^#{1,3}\s+" + re.escape(section) + r"\s*$", l):
                idx = i
                break
    if idx is None and section:
        return text.rstrip("\n") + f"\n\n## {section}\n{line}\n"
    if idx is None:
        return text.rstrip("\n") + f"\n{line}\n"
    # insert as the first bullet of the section, after the heading and one blank
    at = idx + 1
    while at < len(lines) and not lines[at].strip():
        at += 1
    lines.insert(at, line)
    return "\n".join(lines).rstrip("\n") + "\n"


def rule_patch(target, draft):
    """Unified diff that adds one rule line; the resident file is only read."""
    target = normalize_target(target)
    path = os.path.expanduser(target["file"])
    old = Path(path).read_text() if os.path.exists(path) else ""
    new = insert_rule(old, target["section"], draft, target["file"])
    if old == new:
        return (f"# no change: the rule is already present in {target['file']}\n")
    diff = difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                fromfile=target["file"] if old else "/dev/null",
                                tofile=target["file"], n=3)
    return "".join(diff)


def ensure_registered(wiki, language="zh"):
    """Put the generated page into misc/README.md once."""
    wiki = Path(wiki)
    readme = wiki / "misc" / "README.md"
    text = readme.read_text() if readme.exists() else "# misc\n"
    if "(rule-candidates.md)" in text:
        return False
    desc = "规则候选（由结构化记录生成）" if language == "zh" else "rule candidates (generated from structured records)"
    if not text.endswith("\n"):
        text += "\n"
    readme.parent.mkdir(parents=True, exist_ok=True)
    readme.write_text(text + f"- [rule-candidates](rule-candidates.md) — {desc}\n")
    return True


def render_page(records, language="zh"):
    """Render the human page from the records; deterministic for a given store."""
    zh = language == "zh"
    description = "规则候选：来自 dream 的结构化记录，由用户决定接受或否决" if zh else \
        "rule candidates from dream, for the user to accept or reject"
    scope = ("dream 归纳的规则候选、用户的接受/否决记录和补丁路径；由 bin/ingest.py proposals 生成，不手改"
             if zh else
             "rule candidates, the user's accept/reject decisions and patch paths; generated by "
             "bin/ingest.py proposals, do not edit by hand")
    out = ["---", "name: rule-candidates", f"description: {description}", "metadata:", f"  scope: {scope}",
           "---", "# 规则候选" if zh else "# Rule candidates", ""]
    open_records = [r for r in records if r.get("status") == "open"]
    once = [r for r in open_records if len(r["occurrences"]) < MIN_OCCURRENCES]
    proposed = [r for r in open_records if len(r["occurrences"]) >= MIN_OCCURRENCES]
    accepted = [r for r in records if r.get("status") == "accepted"]
    rejected = [r for r in records if r.get("status") == "rejected"]

    if once:
        out.append("## 关键事实" if zh else "## Key facts")
        for r in once:
            o = r["occurrences"][0]
            pattern = clip(r.get("draft") or r["key"], 80)
            out.append(f"- {o['date']} {o['sid8']} {pattern}：「{clip(o['quote'], 100)}」")
        out.append("")
    if proposed:
        out.append("## 待办" if zh else "## Open items")
        for r in proposed:
            target = target_label(r["target"])
            line = (f"- 是否把「{clip(r['draft'])}」加进 {target}（或做成 hook/测试）："
                    f"出现 {len(r['occurrences'])} 次；dream 建议，用户未答复"
                    if zh else
                    f"- Whether to add 「{clip(r['draft'])}」 to {target} (or make it a hook/test): "
                    f"seen {len(r['occurrences'])} times; dream suggestion, no answer yet")
            out.append(line)
            for o in r["occurrences"]:
                out.append(f"  - {o['date']} {o['sid8']}「{clip(o['quote'], 100)}」")
        out.append("")
    if accepted or rejected:
        out.append("## 决策与踩坑" if zh else "## Decisions & pitfalls")
        for r in accepted:
            line = (f"- 已接受 {r['id']}：「{clip(r['draft'])}」→ 补丁 `{r['patch']}`（规则文件未改）"
                    if zh else
                    f"- Accepted {r['id']}: 「{clip(r['draft'])}」 → patch `{r['patch']}` (rule file untouched)")
            out.append(line)
        for r in rejected:
            line = (f"- 已否决 {r['id']}：「{clip(r['draft'])}」" + (f" — {r['reason']}" if r.get("reason") else "")
                    if zh else
                    f"- Rejected {r['id']}: 「{clip(r['draft'])}」" + (f" — {r['reason']}" if r.get("reason") else ""))
            out.append(line)
        out.append("")
    if not (once or proposed or accepted or rejected):
        out.append("## 待办" if zh else "## Open items")
        out.append("- 暂无候选" if zh else "- no candidates yet")
        out.append("")
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


def publish(store, wiki, language="zh"):
    """Write the generated page and register it; returns (page_path, changed)."""
    wiki = Path(wiki)
    page = wiki / PAGE
    page.parent.mkdir(parents=True, exist_ok=True)
    text = render_page(store.records, language)
    changed = not page.exists() or page.read_text() != text
    if changed:
        page.write_text(text)
    ensure_registered(wiki, language)
    return page, changed


def list_text(store):
    rows = store.list()
    if not rows:
        return "no proposals"
    lines = [f"{'id':10} {'status':9} {'n':>2}  target / draft"]
    for r in rows:
        lines.append(f"{r['id']:10} {r['status']:9} {len(r['occurrences']):>2}  "
                     f"{target_label(r['target'])} — {clip(r['draft'], 60)}")
    return "\n".join(lines)
