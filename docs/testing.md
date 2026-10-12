# Validation and remaining limits

Release 0.1.0 was locally checked on macOS with Python 3.9.6 and 3.12.14:

- 12 installer/runtime unit tests: preserving configuration, idempotence, uninstall ownership, changed matchers, symlink rejection, interrupted copies, real installer invocation, plugin deduplication, bounded context, frozen plans, declared retries and deterministic ZIP building.
- 15 learning tests: exact scoped approval, backups, size bounds, concurrent writers, projection integrity, rejected symlink/nonregular paths, failed commit rollback and interrupted-approval recovery.
- Independent subprocess checks in two fresh synthetic user homes: Codex and Claude configuration install/reinstall/uninstall; no-plan Write denied, valid plan accepted, allowed Write, outside Write denied, observed path, one corrective Stop and fresh literal file acceptance.
- Distribution and plugin archive inspected for personal identifiers, original user data and credential patterns. Private deployment journals, screenshots, account files and real preferences are not included.

Run the suites yourself:

```sh
python3 -B -m unittest discover -s tests -v
python3 -B -m unittest discover -s learning -p 'test*.py' -v
python3 tools/build_plugin.py
```

CI repeats the suites and build on macOS/Linux with Python 3.9/3.12. A CI job is not evidence of platform hook activation. The neutral public package has not been freshly exercised through every supported desktop UI; each installation needs its own native trust and activation check. Windows, arbitrary remote/MCP write tools, automatic model routing, full transcript learning and live cloud policy synchronization are not validated features.
