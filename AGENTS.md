## Rules
- Single Source of Truth of domain and configurations: No manual synchronization.
- Use `grounding-before-coding` before non-trivial investigation or change.
- Don't hide confusion; surface tradeoffs and unresolved intent.
- Fail Loud: "Completed" is wrong if anything was skipped silently. Default to surfacing uncertainty, not hiding it.
- Reduce comments: Avoid comments unless absolutely required to explain unusual or complex logic.
- NO `__init__.py` is allowed

## Git
- Both `~/PyCharmProjects/Segdete/.lsml` and `~/PyCharmProjects/Segdete/.git` manages the project of mumbo and point to two distinct remote github repos respectively
- `.lsml` manages `.agents`, `docs/lsml`, `lsml`, `.opencode/plugins`, CONTEXT.md, AGENTS.md; `.git` manages `backend`, `frontend`, `deploy`, `rulechains`, `docs/mqtt` and `docs/segdete`
- `git config --global alias.lsml` returns `!git --git-dir=~/PyCharmProjects/Segdete/.lsml --work-tree=~/PyCharmProjects/Segdete`
