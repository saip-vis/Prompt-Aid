# Supervised Build mode (0.2 prototype)

Build mode is opt-in. Prompt Aid owns a bounded Codex worker process, a detached
Git worktree, a persistent event log, and the completion checks you approve. The
existing fast prompt-review skill remains available and never starts a build.

## Start

Use an installed, signed-in Codex CLI (`codex login status`). No separate API key
is required when using its ChatGPT login. Worker usage counts against that account.

```sh
.venv/bin/python -m backend.manage start --root /absolute/clean/git/project
python3 scripts/install-local.py
python3 skill/prompt-aid/review.py build
```

Double-clicking the native app without a review payload opens the same Build
window. A running configured local workspace is required. If the service was
already running before upgrading, stop/start it to load the Build routes. Only
previously configured project roots are selectable.

Describe the change in **What would you like to build?**. Optional instructions
live under **Anything to preserve or avoid?**. **How we’ll check the changes**
suggests named test suites from the selected project. One suite is selected by
default (Python first for mixed projects); select any additional suites you want.
**Show command** reveals the exact command and its source. No commands, imports,
model calls, or dependency installations happen during discovery.

Detection reads bounded `package.json` scripts/lockfile metadata, Python test
settings or a small sample of test files, and Swift package/test directories.
It respects the configured project allowlist and does not follow symlinked
manifests or test directories. This is a best-effort suggestion, not a guarantee
that dependencies are available or that the suite covers your goal. Detected
command checks have a two-minute timeout each. No recognized tests means a clear
explanation; Build will not silently replace testing with an always-passing check.

**Advanced options** contains a custom command/file check and attempt/time limits.
Commands are executable/argument arrays, not implicitly evaluated shell strings.
Quotes are supported; pipelines need an explicit shell. The native form can
select multiple detected suites or one custom check; the API supports eight.
Check the approval box and choose **Start building**. Editing the goal, checks or
limits clears approval. A readiness message explains a missing Git checkpoint;
**Refresh project checks** rechecks it after you save. Historical builds remain
read-only; **New build from this goal** retains the goal and suggests fresh checks.

The source repository must be clean and have a commit. Prompt Aid never silently
stashes work. It creates a detached worktree under the private data directory;
your original branch and files remain unchanged. Existing `node_modules`/`.venv`
directories may be linked read-only for dependency use. New dependencies are not
installed automatically and direct network access in worker tools is disabled.

## What happens

1. Save the approved goal, constraints, checks, and budgets in SQLite.
2. Create an isolated worktree from the selected source commit.
3. Retrieve at most three relevant starting-code excerpts from that worktree.
4. Start a Codex CLI turn with the approved scope and stream structured progress.
5. Independently run the approved checks, including command checks inside a named
   Codex filesystem/network sandbox. A worker's “done” statement is insufficient.
6. If a check fails, send its bounded output back as evidence for a targeted retry.
   Identical failures with unchanged diffs stop the loop. No evaluator model is
   called while the worker is making progress.
7. Passing checks produces **Checks passed** and a diff preview for your review.
   This is evidence for the criteria you selected, not proof of all possible
   behavior or semantic correctness. Nothing is automatically committed, merged,
   pushed, deployed, or sent to another person.

Each worker turn is a new ephemeral CLI process that sees the same approved goal,
current worktree, and latest failure evidence; this prototype does not control an
existing GUI chat or replay all of its conversation. Model/tool-output text is
untrusted evidence. The controller does not persist reasoning events. Structured
summaries, test output, usage counts, goals, and changes are retained locally.

## Controls and persistence

- **Stop build** cancels the active process group and prevents another turn. It
  retains completed edits in the worktree; it does not roll back completed actions.
- A watchdog kills the owned worker/check process if the controller exits or its
  deadline expires. Restart marks interrupted sessions as needing input; it never
  automatically resumes them. Storage has one process owner.
- Questions pause execution. If approved turns remain, enter a clarification and
  approve continuation; the same worktree is retained. The original goal/checks
  stay fixed. A fresh time allowance is explicitly approved by that action.
- The default budget is three worker turns and ten minutes. UI limits are one to
  five turns and one to thirty minutes. Per-command checks also have a timeout.
- The UI prevents closing an active build window before Stop. A normal app quit
  requests Stop and waits for confirmation; force-killing only the UI does not
  stop a service-owned build. Its configured budgets still apply.
- **Previous builds** shows project-scoped records. Diff previews are bounded;
  inspect the retained worktree for large/binary changes. No destructive cleanup
  runs automatically. Remove an unwanted worktree with Git only after review.

The named `promptaid` profile extends Codex's workspace profile, limits command
reads/writes to the worktree, approved temporary/dependency paths and runtime
resources, denies common credential paths, and denies direct tool network access.
The CLI/model transport and Git/worktree orchestration run outside that subprocess sandbox. Custom executables,
project tests and Codex are trusted runtime dependencies, not an isolated VM.
Managed Codex policy can reject the profile; the controller fails rather than
falling back to unrestricted execution. Supported CLI behavior was checked using
`codex exec --help`, `codex sandbox --help`, and the official
[permission-profile documentation](https://learn.chatgpt.com/docs/permissions).

## API

All routes use the existing private loopback bearer authentication and reject
browser-origin requests. There is no MCP tool for silently approving a build.

| Route | Purpose |
|---|---|
| `GET /builds/config` | Allowed roots and worker availability |
| `GET /builds/suggestions?root=...` | Read-only suggested checks and Git readiness for one allowed project |
| `GET /builds` | Recent builds within configured roots |
| `POST /builds` | Explicit approved specification and limits |
| `GET /builds/{id}` | Current state and check outcomes |
| `GET /builds/{id}/events?after=...` | Bounded structured events |
| `GET /builds/{id}/diff` | Bounded tracked/untracked diff preview |
| `POST /builds/{id}/stop` | Cancel without a next turn |
| `POST /builds/{id}/resume` | Explicit clarification with time allowance |

Build records live in `<data>/builds/builds.sqlite3`; worktrees and worker reports
live in `<data>/builds/<id>/`. Treat these as private project data. Current memory
is the approved specification, progress/check history, current worktree and
project-scoped prior builds. Automatic cross-build preference learning, model
weight updates, continuous screen recording, autonomous visual evaluation, and
auto-merge are not implemented in this first version.

## Verification

```sh
.venv/bin/python -m unittest discover -s test -p 'test_builds.py' -v
swift test
# Opt-in: uses the signed-in Codex account on a disposable local fixture:
.venv/bin/python scripts/smoke_build.py
```

The real smoke test fixed a broken addition function in a detached worktree and
passed an independent sandboxed unittest, while the source fixture stayed broken
and unchanged. Controller tests additionally exercise correction, stalls, budgets,
questions/continuation, cancellation, authentication, project isolation, unsafe
check paths, restart behavior, and controller-death watchdog cancellation.

### Review startup check

Build has its own `PromptAidBuild` executable; review payloads continue through the
small `PromptAid` executable without loading the Build UI. A five-launch local
check measured 650 ms for the first launch and a 364 ms warm median (374, 377,
354, 347 ms). This measures a prepared JSON payload to first window display plus
the next main-queue turn, at 5 ms polling resolution; host LLM/preparation latency
is excluded. Earlier optimized-review measurements were roughly 659 ms first and
332 ms warm, so these samples support preserving startup behavior, not a new
speedup claim. Raw measurements are local at
`/tmp/prompt-aid-split-review-launch.json`.
