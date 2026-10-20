# Strict project hygiene: accepted boundaries and remaining gaps

Status: **Open for universal customer rollout**. This is an explicit opt-in implementation, not a guarantee that every host action or every semantic dependency is covered. Written instructions alone do not enable it.

## Installation and activation

From a reviewed checkout containing this feature:

```sh
python3 install.py --platform codex --hygiene-enforcement
python3 install.py --platform claude --hygiene-enforcement
```

Use `--home /absolute/disposable/home` first to test configuration without activating your real account. The installer preserves other configuration and recoverable previous runtime bytes. Strict mode is disabled unless explicitly enabled. A native client must load the configured hooks; Codex requires its native hook trust review. A saved JSON file or installer success is not activation evidence. Project settings, managed settings or host restrictions can disable hooks.

The opt-in policy is local to each host installation: Codex uses its kit `state/hygiene-policy.json`; Claude Code uses its kit `hygiene-policy.json`. It applies to covered calls in every valid project root routed through that installation, with no project age filter. This is not evidence that all already-open sessions or all existing projects have adopted the installation. Uninstall retains runtime/policy files for recovery; review retained policy before reinstalling.

## Executable workflow

Within the native hooked shell tool, use exact standalone sentinels. They are intercepted by PreToolUse, not installed shell executables. A denial containing an inspection result or `Hygiene review accepted by code` is expected; the sentinel must not reach the shell.

1. Prepare the existing workflow ledger's actual acceptance plan.
2. Inspect exact targets: `workflow-hygiene inspect '{"paths":["notes.txt"]}'`. Returned hashes are observations, not approval.
3. Submit `workflow-hygiene review '<JSON>'` before editing. Each entry needs `path`, `decision`, the current `sha256` (or null for a new path), `reason`, `usage`, `dependencies`, and `concurrency`.
4. A supported edit is allowed only after preflight. Existing bytes are copied and hash-verified under the same project's dated `Old/YYYY-MM/<unique>/files/<relative-path>` before authorization. New paths have no previous version to archive.
5. The next supported edit and Stop remain blocked until actual post-edit hashes and review decisions are accepted. Repeated `stop_hook_active` does not turn missing review into a pass in this handler.
6. Complete the workflow ledger's actual QA as well. Hygiene approval does not replace output QA.

Example review body:

```json
{
  "entries": [{
    "path": "notes.txt",
    "decision": "keep",
    "sha256": "COPY_THE_ACTUAL_INSPECTED_SHA256_HERE",
    "reason": "Current requested deliverable",
    "usage": "Describe the actual use that was inspected",
    "dependencies": "Describe checked local and declared external dependencies",
    "concurrency": "Describe the checked concurrent work"
  }]
}
```

Nonempty notes are required but are not authenticated semantic proof. An `uncertain` decision remains a blocker; ask the operator instead of guessing. Required source, tests, configuration and dependencies retain the locations the project needs. Helpers may be classified as `asset`; supported unreferenced media/document assets relocate to `Assets/<relative-path>` with a verified recovery copy. A protected or unresolved dependency prevents transfer.

`archive` is intentionally narrower than “all obsolete files”: only explicitly reviewed, byte-identical supported media/document duplicates with a distinct kept canonical file and no detected local literal references are eligible. Supply `canonical` and its `canonical_sha256`. Source/configuration/credential/lock names, symlinks, same-inode aliases, unknown scan inputs, collisions, concurrent changes and exceeded bounds are refused. A dated manifest records the reason and hashes. No permanent deletion occurs; the live duplicate is removed only after its recoverable copy is verified.

Restore through `workflow-hygiene restore '{"manifest":"Old/YYYY-MM/<unique>/manifest.json"}'`. The original destination must be absent. Restoration verifies archive bytes, never overwrites a live file and requires review afterwards. The manifest belongs to this hygiene guard; do not mix it with an unrelated archiver's manifest schema.

## Deliberate restrictions

Strict mode rejects shell commands other than valid intercepted sentinels, including commands conventionally called read-only and ordinary build or generation commands. PATH resolution, shell startup and project configuration can execute code; shell-name heuristics are not a verified write boundary. Use native supported reads/file tools or the bounded intercepted `workflow-hygiene read` sentinel; it returns a real hash and at most 8,000 UTF-8 characters, with optional character offset. Use a separately reviewed integration for commands that require writes. Shell aliases are normalized before both hygiene and the baseline ledger gate. Chained or malformed sentinels are denied. This restriction is real friction and must be evaluated before enabling strict mode on a customer's normal build workflow.

This implementation does not prove interception of arbitrary MCP/connector effects, native paths that omit PreToolUse, external editors, other machines or deliberate same-account tampering. It does not infer that a file is obsolete from age/name, or prove all dynamic/external dependencies. Literal-reference absence is not semantic nonuse. Hosts can impose their own Stop-continuation limits; the kit cannot promise an unbypassable completion boundary beyond the host contract.

Bounds are explicit refusals, not silently partial approval: at most 128 paths per review/edit, 512 tracked paths per session/project, 16 MiB per file, and a reference scan capped at 2,000 files / 16 MiB. Old, Git metadata and conventional dependency directories are excluded from the local reference scan. A larger/unrecognized project requires review rather than a false green result.

## Acceptance evidence

See [the native hygiene acceptance record](acceptance/2026-10-20-hygiene.md). Native experiments used disconnected disposable projects and subscription authentication only. They prove specified guard branches, not automatic global deployment or a universally correct cleanup decision. [Codex instructions](../rules/HYGIENE-CODEX.md) and [Claude Code instructions](../rules/HYGIENE-CLAUDE.md) are supporting contracts, not executable enforcement.

## Supporting customer instructions

Hebrew instruction payloads are available for [Codex](../prompts/hygiene-codex.he.txt) and [Claude Code](../prompts/hygiene-claude-code.he.txt). They explicitly require an installed, verified executable gate and preserve the open universal-coverage status. These texts alone do not install hooks or create deterministic enforcement.

## Cycle 2 hardening

Pre/Post matchers now cover every delivered tool event. Strict mode uses full native identities and rejects unknown connectors/interpreter wrappers rather than trusting a native-looking suffix. Native read tools remain available. Invalid, oversized or non-object callback input exits 2; receipt failures deny PreToolUse or block Stop. Claude PreToolUse also sets `onFailure: block`. Runtime failure behavior still depends on host support. Installed hook commands explicitly bind HOME to the installation target, including alternate homes. See [cycle 2 acceptance](acceptance/2026-10-20-hygiene-cycle2.md) and [customer installation](customer-install.md).
