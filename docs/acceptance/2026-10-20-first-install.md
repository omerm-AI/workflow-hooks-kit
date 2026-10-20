# First-time external installation acceptance

Date: 2026-10-20. Reviewed runtime preview: `hygiene-preview-2026-10-20`, commit `ff5daf388b6589733e2eca80bcdfabb5e7454afa`. Later documentation-only changes do not alter the runtime snapshot.

| Check | Codex | Claude Code | Evidence/reason |
|---|---|---|---|
| Fresh public HTTPS clone, exact remote tag/commit | Tested and proven | Tested and proven | No local source substitution; detached immutable preview checkout. |
| Actual recorded installer-command lifecycle in disposable homes | Tested and proven | Tested and proven | Four cases passed: new/populated roots, original backup hash, next-edit denial, Stop block/release, unknown-tool refusal and required source preserved. Model calls: zero. Harness performs file writes between callback invocations; this is not native-client inference. |
| Installer leaves a pre-existing project unchanged | Tested and proven | Tested and proven | Fixture project existed before install; its bytes were retained and no Old folder created by installation. |
| Explicit hook HOME isolated from caller HOME | Tested and proven | Tested and proven | Actual configured command ran under a different caller HOME; private state/receipts appeared only under the installation home. |
| Native actual installed PreToolUse command | Open | Tested and proven | Claude unchanged installer command denied an actual Write for missing hygiene preflight. File absent; three installed-main native-ID/source-bound receipts verified. One subscription inference request, no API-key fallback. |
| Staging configuration discovery | Tested and proven | Tested and proven | Codex CODEX_HOME profile discovered four hooks from its own config; Claude loaded the explicit staging settings in its separately measured native trial. |
| Global operator deployment and all already-open sessions | Open | Open | Existing operator sources and single scope handler/event are staged recoverably; strict policy remains disabled. The operator approved the Codex definitions; read-only native discovery confirmed they are trusted. The operator explicitly chose to keep global strict off until a safe testing path and separate native acceptance exist. No complete adoption claim. |

The Claude test-only UPS bootstrap submitted a genuine compact baseline plan using observed native IDs through the actual installed core. It supplied no hygiene review and did not replace the installed Pre/Stop entrypoints. Stop blocked baseline pending QA after the denied Write; it is not represented as a pending-edit hygiene Stop. A disclosed observer synthetic empty answer allowed real Stop at the one-request cap. Parent subscription authentication retained its original home; only the installed hook process used the staging HOME. Observed instruction-file/MCP/skill inventories were empty and vendor sections remained unchanged.

Native successful overwrite, byte-exact Old and next-edit denial were separately measured in [cycle 2](2026-10-20-hygiene-cycle2.md). Installation/source verification is distinct from native activation, full automation, semantic dependency correctness and universal future coverage. Runtime startup failures and unsupported host paths are not an operating-system sandbox guarantee.

No raw local paths, native IDs, account metadata, secret material, private logs or vendor prompt contents are published. Customer-facing source, commands and scope are linked in [the installation guide](../customer-install.md).

The fresh Codex profile was logged out and its definitions untrusted. No credential copying, API login, thread/turn start or inference was attempted there. Its native canary remains Open until normal subscription login, user hook trust and actual callbacks are evidenced; the existing operator account cannot stand in for that proof.
