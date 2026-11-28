# Creator-offer evidence demo

Prompt Aid supervises a coding change in a separate fictional Creator Inbox
repository. Twelve synthetic messages exercise budgets, currencies, deadlines,
deliverables, ambiguous/conflicting values, and instructions embedded in source
text. The seed extractor is intentionally flawed. No real creator data, outbound
email, CRM access, scraping, or model training is involved.

## Set up

```sh
.venv/bin/python scripts/setup_creator_demo.py
.venv/bin/python -m backend.manage stop
.venv/bin/python -m backend.manage start \
  --root "$PWD" --root "$PWD/.prompt-aid/creator-inbox"
python3 scripts/install-local.py
python3 skill/prompt-aid/review.py build
```

Retain any other explicitly configured roots/model arguments when restarting your
service. Setup refuses to overwrite an unrelated nonempty directory, and reuses
an existing marked demo without resetting its work. Models are optional for local
retrieval; a real Build still needs the signed-in Codex CLI.

Choose **Creator-offer demo**. This fills the goal, constraints, four criteria,
and four protected checks. Review them and approve **Start building**. It measures
the seeded code before starting the worker, then checks each worker result against
the same frozen examples. A coding worker may use account quota. Loading a preset,
viewing evidence and replaying snapshots do not call a model.

## What is protected

The controller copies its bundled `creator-offers-v1` pack and input messages into
`<data>/builds/<id>/verification/`, outside the worker-writable worktree, and records
its SHA-256. The extractor runs in the existing filesystem/network sandbox with
read access to the input file. Expected answers and the evaluator are not writable
by the worker. The evaluator is controller code, not a test script from the target
repository. Editing the project's inbox, tests or output files does not change
these frozen inputs or expected answers. Tampering with either snapshot blocks
checks; a recheck retains the original pack, rather than silently adopting new
expectations. These are finite, bundled examples, not a secret or real-world
benchmark; a model can still overfit them. Human confirmation remains explicit.

A `creator_offer` check approves the relative `.py` extractor path and a fixed
rule (`budget`, `currency`, `deadline`, `source_evidence`). The controller invokes
its installed Python with isolated imports and a frozen JSON input path, and
checks JSON stdout. It runs the extractor once per check phase, reusing that
output for four independent rule verdicts. Outputs are bounded; malformed JSON,
non-finite values, duplicate/missing IDs and unsupported facts cannot pass.

Each verdict records case ID, expected/actual values and the source excerpt.
`criterion_indices` links each check to the approved success criteria. Automated
support is displayed beside each criterion; it does not substitute for a user's
observation or automatically mark the whole task verified. Worktree freshness and
explicit Run/Cancel/Stop behavior remain unchanged.

## Compare and replay

Open the completed run, then **Compare & replay recorded evidence**:

- Starting-code and latest snapshots show checks and source assertions passed.
  Twelve messages each receive four rule verdicts, so there are 48 assertions.
- Phase durations are measured wall time for that check/worker-result phase.
  Coding-worker duration is separated; token counts are cumulative reported usage.
  Cached-input counts appear only when reported. No dollar-cost estimate is made.
- Replay steps are saved snapshots with actual output previews (first three
  offers), verdicts and metrics. The UI explicitly labels recorded replay.
- Cross-run selection is restricted to the same project. Matching metadata does
  not establish a controlled model comparison: worker model/settings are not
  pinned. Different commits/checks/goals/budgets receive an explicit caveat.
- Older intermediate steps can be omitted to bound history; the seeded baseline
  and latest steps are retained. Historical runs without snapshots remain
  unavailable, rather than receiving fabricated baselines.

This compares seeded code with actual worker results. It does not establish that
Prompt Aid outperforms an unaided LLM. A separate matched experiment would be
needed for that claim.

## Two-minute walkthrough

- **0:00–0:15:** Explain the problem: extracted deal terms need source evidence.
- **0:15–0:35:** Show the approved goal, criteria and protected checks.
- **0:35–1:05:** Use the recorded baseline; expand `missing-budget` to show an
  invented amount against an expected unknown value. Label this as recorded.
- **1:05–1:35:** Advance replay to the real worker result and inspect the same
  assertion and actual output. Discuss any failures honestly.
- **1:35–2:00:** Show remaining human-review items and one measured result.
  Explain that the coding model implements changes while your controller owns
  scope, execution limits, persistence and independent evidence.

## Integration

Authenticated routes include `GET /builds/demo`,
`GET /builds/{id}/comparison` (optional `baseline_id`), existing cursor-based events,
and approved Build/recheck actions. The TypeScript client in `sdk/typescript`
provides typed Node.js/desktop access to the Python API. It uses private bearer
headers, loopback-only destinations, bounded responses and no redirects. The
service rejects browser-origin requests; do not put its token in a browser app.

```sh
npm run test:sdk
.venv/bin/python -m unittest discover -s test -p 'test_creator_checks.py' -v
```

## Measured development run

One real signed-in Codex run moved the seed from **32/48 assertions (0/4 complete
checks)** to **48/48 assertions (4/4 checks)** in one coding attempt. Baseline
checking took 0.29 seconds; the worker-result phase took 83.26 seconds, including
82.95 seconds in the coding worker. The run reported 147,327 cumulative input
and 3,701 output tokens, with 119,680 cached input tokens. These are local,
fixture-specific observations, not a performance promise or an estimate of cost.
The result remained **Needs review**; no human confirmations were fabricated and
nothing was merged into the original demo project.

A prior real run exposed an accounting integration bug and is retained as failed
history. It is not presented as a successful model comparison. The corrected run
and its snapshots are available in the local app's project-scoped build history.
