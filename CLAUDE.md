# Operating rules

Repository facts, layout, and build commands live in @AGENTS.md. Frontend
conventions live in @frontend/AGENTS.md. This file is the operating harness:
how to work, not what the project is.

Adapted from the Prime Agent development rules
(https://github.com/PrimeIntellect-ai/prime-agent, MIT). Their monorepo-specific
rules — npm, `packages/ai`, daemon protocol, changelog format — do not apply
here and were dropped.

## Style

- No fluff, no cheerful filler, no preamble. Technical prose only.
- Kind but direct. "Thanks @user", not "Thanks so much @user!".
- No emojis in commits, issues, PR comments, or code.
- Short answers. Report what you changed, what you verified, and what is still
  broken or unverified.

## Code quality

- Read files in full before wide-ranging changes, before editing a file you
  have not already fully inspected, and whenever asked to investigate or audit.
  Search snippets are not enough for broad changes.
- Comment only where there is real ambiguity. Do not narrate the code.
- No bare `Any` in Python or `dynamic` in Dart when a real type exists.
- For external library signatures, read the installed source
  (`backend/.venv/lib/python3.12/site-packages/...`) instead of guessing.
- Never delete, weaken, or downgrade code to silence a type or lint error. Fix
  the cause, or upgrade the dependency.
- No function-level imports except to break a genuine import cycle. Prefer
  top-level imports.
- Always ask before removing functionality that looks intentional.
- Do not preserve backward compatibility unless explicitly asked.

## Verification

- After backend changes, run the suite. In Docker:
  `docker compose --profile test run --rm --build backend-test`.
  On the host: `cd backend && PYTHONPATH=src .venv/bin/python -m pytest -q`.
- After frontend changes: `cd frontend && dart format lib test && dart analyze
  && flutter test`. Use `dart analyze`, never `flutter analyze` — it crashes in
  this checkout (see Paths below).
- If you create or modify a test file, you MUST run that file and iterate until
  it passes. Do not hand back a test you have not executed.
- A backend change reaches the running stack only after the affected container
  is rebuilt: `docker compose up -d --build worker store-sync-worker`. Workers
  run their own image; skipping this leaves scraping and pricing on stale code.
- Say which claims you executed and which you only read. Name what you did not
  verify. Never claim production readiness from a local run.

Treat the suite for the layer you touched as a gate, not as a formality: it has
to pass before you report the work done. If it fails, the failure output is the
next input — read it and iterate. If you are going to stop with it still red,
say so in the first sentence rather than burying it under what did work.

## Git rules for parallel agents

Multiple agents may work in this worktree at once.

- Commit ONLY the files you changed in THIS session. Track them as you go.
- NEVER `git add -A` or `git add .` — they sweep up other agents' work. Always
  `git add <specific-path>`.
- Run `git status` before committing and verify you are staging only your files.
- Forbidden, they destroy uncommitted work: `git reset --hard`, `git checkout .`,
  `git clean -fd`, `git stash`, `git commit --no-verify`.
- On rebase conflicts, resolve only in your files. If the conflict is in a file
  you did not touch, abort and ask.
- Never force push. Commit and push only when asked; if on the default branch,
  branch first.

## Dependencies

- Backend dependencies go through `uv`. A `pyproject.toml` change must be
  committed together with the regenerated `uv.lock`.
- Prefer releases at least 7 days old. For an urgent security patch, say so
  explicitly and pin the exact version.

## Paths and scratch files

- This repository's directory name contains a non-breaking space (U+00A0)
  between `marko` and `копия`. U+00A0 renders exactly like an ordinary space in
  terminal output, so a path copied by eye is a *different* path: reads fail,
  and writes silently create a phantom twin directory instead of failing.
  Copying it out of a previous tool result does not help.
- In shell, reach the repository with a glob or tab completion, never by typing
  the name: `cd /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko*копия`.
- A glob does not help file tools that need a literal absolute path. Create an
  ASCII symlink once per session and route every Read/Write/Edit path through
  it. The `is_dir()` filter matters — a same-prefixed `.zip` backup sits next to
  the real directory:

  ```bash
  python3 -c "import pathlib,os;b=pathlib.Path('/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko');r=[p for p in b.iterdir() if p.is_dir() and p.name.encode().startswith(b'marko\xc2\xa0')][0];os.path.islink('/tmp/marko_ascii') and os.unlink('/tmp/marko_ascii');os.symlink(r,'/tmp/marko_ascii')"
  ```

- Detection, cheap and definitive — must print `1`:

  ```bash
  ls -d /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko*копия | wc -l
  ```

  If it prints `2`, a phantom exists. Check its contents, move anything real
  into the repository, remove the empty shell. Distinguish the two by bytes,
  never by eye: real is `marko\xc2\xa0\xe2\x80\x94`, phantom is
  `marko\x20\xe2\x80\x94`.
- Never name a scratch or probe file after a stdlib module (`math.py`,
  `inspect.py`, `types.py`) inside `backend/src`, `backend/tests`, or
  `scripts/`. It shadows the real module and looks like a bug in the code
  under test.

## Formal stage reports

Do not emit the Section 15.1 `STAGE_RESULT` / `BLOCKERS` / `NEXT_STAGE` /
`STOP_GATE_*` footer or a Section 16 `MACHINE_READABLE_SUMMARY` block by
default. That contract is retired for ordinary work. Generate one only when
someone explicitly asks for a stage report, using the validators in
`backend/src/marko/governance/`.

## Harness state

Durable agent state lives in the repository, not in a single conversation:

- `.claude/skills/<name>/SKILL.md` — a workflow that recurs. When you find
  yourself repeating a multi-step procedure, propose turning it into a skill.
- `.claude/agents/<name>.md` — a reusable subagent spec for delegated work.
- `.claude/settings.json` — permissions and hooks, shared with the team.
  `.claude/settings.local.json` is personal and untracked.

A skill is a directory with `SKILL.md` (YAML frontmatter: `name`, lowercase and
hyphenated, matching the directory; `description`, up to 1024 chars), plus
optional `scripts/`, `references/`, `assets/` referenced by relative path. The
`description` is the whole selection mechanism — it decides whether the skill is
ever invoked. "Helps with pricing" is useless; name the concrete operations and
the situations that should trigger them. Keep `SKILL.md` short and push detail
into `references/`, loaded only when needed. Project skills go in
`.claude/skills/` and are committed; personal ones live under `~/.claude/`.

## Delegation

Prefer doing the work directly; do not spawn subagents unless asked. When
delegation is warranted, spawn independent subagents in one batch rather than
awaiting them one at a time — three focused reviewers in parallel beat one
sequential pass. Give each a self-contained brief: a subagent starts cold and
cannot see this conversation. Their reports come back to you, not to the user,
so relay what matters instead of assuming it was seen.

## Refining these rules

Improve this file through small, evidence-backed edits: change a rule only
after a concrete failure in this repository showed it was wrong or missing, and
say in the commit message which failure justified it. Do not rewrite the file
wholesale.

## Override

If a user instruction conflicts with a rule here, say which rule it conflicts
with and ask for confirmation before overriding it. Once confirmed, proceed
with the full instruction.
