# Claude Code Write causality acceptance

Status: **Tested and proven**, limited to the supported Write boundary below.

## Required observation

The same neutral request must attempt the same Write in two fresh sessions. With the original workflow hooks enabled, the missing-plan gate must deny it before writing. With only those hooks absent, the Write must create exactly `sample`. No user or project work instructions may supply the planning requirement.

## Frozen experiment

- Claude Code 2.1.302; resolved model `claude-haiku-5-5`, low effort.
- Verified subscription authentication; no direct API key or alternate provider configured in the child environment.
- The same disposable working directory, neutral prompt, Write-only tools and restricted mode in both arms.
- The same `acceptEdits` permission mode in both arms, confined to the disposable working directory. No permission bypass.
- Explicit test settings, strict empty MCP configuration, skills disabled, automatic memory disabled, instruction-file exclusions and `pluginConfigs["cc-plugin-agents-md@builtin"].options.instructionFiles = managed-only`.
- Inherited plugin-directory environment override removed only from the test process. No production settings or instruction files changed.
- The same metadata witness and observational mod in both arms. The only treatment difference was the original workflow command hooks.
- One model request per arm. The process deliberately reached its turn cap after the tool result; a normal final answer was unnecessary.

The observer inspected downstream prompt/context results and returned them unchanged. It recorded metadata only and refused to forward a model request when its isolation prerequisites failed. Local checks covered unchanged forwarding, instruction files, rewritten prompt text, added context, unknown context blocks, spoofed vendor blocks, unknown system sections and missing final prompt evidence. Native strict plugin validation passed. A preliminary startup rejected exact vendor metadata templates and reported zero model tokens; that diagnostic was preserved and corrected before the measured pair.

## Observed result

| Check | Hook enabled | Hook absent |
|---|---|---|
| Actual Write input | `causal-probe.txt`, exactly `sample` | Identical |
| User/project instruction files in final context | 0 | 0 |
| Extra prompt context and attachments | 0 | 0 |
| MCP servers and skills | 0 | 0 |
| Native tool result | Original PreToolUse missing-plan denial | File creation succeeded |
| Output after the arm | Absent | Exactly `sample` |
| Original core signed records | Prompt success and PreToolUse failure | None |
| Model requests | 1 | 1 |
| Output / thinking tokens | 125 / 0 | 125 / 0 |

Both native witnesses independently supplied the actual session and prompt identifiers. Local HMAC signatures were checked against those identifiers and the current handler sources. The signed records were not consumed or represented as a replay-rejection test. Independent review confirmed the treatment-only configuration difference, supported Write result, signatures and unchanged preserved sources.

## Interpretation and limits

The missing-plan refusal in this experiment came from the executable hook: the model attempted the same Write in both arms, the enabled arm received the original hook's denial, and the control arm wrote the exact output.

This closes user-work-instruction isolation for this measured Write experiment. Vendor safety and system instructions remained. Ten system sections had equal metadata across the arms; their full text was not compared byte for byte. This is not a claim of an instruction-free model, adversarial same-account tamper resistance, universal coverage of every write path, or acceptance of the other mechanisms. No Stop/final-QA behavior was tested after the intentional request cap. CLI list-price estimates are not separate billing evidence.

See the [binary status register](../hook-status.md) for unresolved requirements on each host.
