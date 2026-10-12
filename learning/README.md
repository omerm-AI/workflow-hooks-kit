# Local learning CLI

This optional, standard-library-only CLI records manually supplied preference proposals and task outcomes. It does not read chat history, scan transcripts, call a model or API, use a network, install a scheduler, or activate inferred rules. A proposal stays pending until a person explicitly runs `approve --approved`. That flag records the caller's declaration; it is not identity authentication.

By default, private state is stored in `~/.local/share/workflow-hooks-kit/learning/`. Use `--state-dir` before the subcommand to point tests or a separate local profile at another directory. State and generated standards are local and excluded from Git.

```sh
python3 learning/cli.py propose --scope quality --rule "Keep acceptance checks reproducible."
python3 learning/cli.py approve p0001 --approved --approval "Reviewed exact scope and wording"
python3 learning/cli.py failure --capability summarization --task brief --model sample-v1 --evidence manual-review-01 --outcome failure
python3 learning/cli.py report
python3 learning/cli.py maintain
python3 learning/cli.py read --scope quality
```

Scopes are lowercase slugs, limited to 48 letters, digits, underscores, or hyphens. Preference wording is limited to 200 characters; failure fields are bounded and duplicate evidence references are rejected. Avoid entering personal, client, secret, transcript, or other sensitive material. Inputs are manually provided and checks reduce common risks; they cannot guarantee that a human-entered description contains no sensitive information.

An approval appends a scoped standard under the private state directory and keeps the prior version as a backup before replacement. Future kit work can load one policy on demand with `read --scope <slug>`. Reads and maintenance confirm that every generated preference block has a matching approved ID, scope, and exact rule; orphaned blocks left by an interrupted write are refused until the approval command is retried. `maintain` is read-only and idempotent, and it does not repair manual edits. `report` aggregates supplied outcomes by capability, task, model, and outcome, and shows no more than three bullets across counts and approved changes. It makes no routing inference. State updates use a local POSIX file lock so simultaneous CLI writes do not overwrite each other.

If a user wants a recurring review, they can create a weekly reminder in their platform's scheduling UI. For example, Sunday at 09:00 local time could remind them to run `report` and review the result. This package creates no schedule, and this example is not an installed user schedule.

Run the tests from this directory with:

```sh
python3 -m unittest -v test_cli.py
```
