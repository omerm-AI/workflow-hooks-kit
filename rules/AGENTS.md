# Portable workflow policy

For material work, read the installed `WORK_STANDARDS.md` in the host's `workflow-hooks-kit` directory, or the repository's Claude plugin `skills/work-standards/SKILL.md`. Load a relevant optional approved standard only through `learning_cli.py read --scope <matching-scope>` (or plugin `learning/cli.py`), which validates approval against local state. Do not directly read generated Markdown standards. Missing optional standards never authorize fetching private sources.

Prepare a scoped plan before edits. Verify actual outputs, preserve recoverable versions, and state unresolved limitations. Select a cost-appropriate available model; record at most three failed attempts per declared model before reassessing. Never claim automatic model selection, generic MCP write coverage, or cloud standards synchronization.

This file is a template. The installer does not overwrite an existing global or project AGENTS.md. Add a reference in the project instructions when desired.
