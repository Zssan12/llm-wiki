# 记忆 = LLM wiki

自动记忆目录是 `~/wiki`（git），一个分层的 LLM wiki。写入前先读 `~/wiki/CLAUDE.md`（schema）。
- 自上而下读，够用就停：`MEMORY.md`（域）→ `<domain>/README.md`（主题）→ `<domain>/<topic>.md`（事实）。历史和会话 id 在 `~/wiki/log.md`。
- 要记住一件事：更新 `scope` 合适的主题页（没有就按 schema 新建），同步 README/MEMORY.md，追加 log.md，跑 `python3 ~/wiki/bin/lint.py`，然后 commit。
- 不写秘密；只记它存放在哪里。
- 读论文或外部项目前，先 `grep -r <arXiv id|owner/name> ~/wiki`；深读完当场写进 `refs/`（格式见 ~/wiki/CLAUDE.md「阅读摘要」）。
- `~/wiki/bin/ingest.py` 在会话关闭时（SessionEnd hook）和每 30 分钟（空闲会话）提炼会话；wiki 里没有的细节，回原会话查（比如用会话续接工具）。
