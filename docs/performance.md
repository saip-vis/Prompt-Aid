# Startup and persistence measurements

Measured November 27, 2026 on this Apple Silicon Mac, using offline MiniLM
embedding/reranking models. Raw samples: `performance-2026-11-27.json` (local, generated measurement samples).

| Stage | Before | After | Interpretation |
|---|---:|---:|---|
| First measured native invocation to displayed window | 849 ms | 659 ms | Sequential local runs; OS caches were not reset |
| Subsequent native launches, median of four | 337 ms | 332 ms | Essentially unchanged at this sample size |
| Service readiness, first process | 8,116 ms | 388 ms | Models now load on demand |
| Service readiness, restarted process | 4,422 ms | 370 ms | Database persists; model loading deferred |
| First hybrid + reranked query, new process | 716 ms after eager startup | 5,967 ms after lazy startup | Loading cost moves to the first ML request |
| Second hybrid + reranked query, same process | 101 ms | 101 ms | Two-file fixture; not a large-codebase benchmark |

The first updated query reports 5,199 ms of embedding-model loading and 124 ms of
reranker loading. After process restart, the query loaded models again but reused
both stored document vectors with zero document re-embeddings. Query embeddings
are still computed for each query. This is improved readiness, not a claim that
the total cold semantic workload disappeared.

The old skill prepared the entire review before launching the app. The new skill
opens a cancellable pending window before read-only investigation and rewrite
preparation, then publishes the final review atomically. Run stays disabled until
a valid final payload with matching original request/project arrives. Host model
latency is variable and was not benchmarked; no provider speedup is claimed.
Opt-in native events separately expose window readiness and review readiness.

## Reproduce

```sh
# Opens and automatically cancels harmless temporary review windows:
.venv/bin/python scripts/benchmark_launch.py --out /tmp/launch.json
# Starts/stops temporary local services with a two-file temporary Git project:
.venv/bin/python scripts/benchmark_service.py --out /tmp/service.json
```

Baseline native samples were collected from the pre-change source with the same
instrumentation and unoptimized Swift compilation. `--baseline` on the current
script only disables optimization; it does not reconstruct the old implementation.
The native endpoint is `displayIfNeeded` plus one main-queue turn, observed by a
5 ms polling loop. It is not a hardware frame-presentation timestamp. First-run
measurements are not cold-boot statistics. No remote model call or API key is
needed for either benchmark.

## Persistence and installed-app checks

- Real local Qdrant plus deterministic embeddings: a separate Python process
  reused both stored chunks without document embedding. Edits replace only the
  changed chunk, including reuse of an untouched block in the same edited file; deletions and new ignore rules prune stored points. Another
  project's collection remains unchanged.
- Offline MiniLM integration and two fresh HTTP service processes verify real
  semantic retrieval/reranking, persistent reuse, and loaded/configured states.
- Actual PromptAid checkout: initial hybrid context request embedded 224 chunks
  in 9.36 s including model loading/index construction; the next subprocess call
  reused all 224 in 348 ms wall time. Later source edits correctly caused targeted
  re-embedding. These numbers are an example, not a universal latency guarantee.
- Installed native UI: pending Run disabled; final review updated in place;
  private connection auto-discovered; reconnect reused service; context search
  displayed reuse/removal counts and verified source cards. Editing the suggestion
  returned exactly `UI verification only; do not execute.` to the test harness.
  Cancel was also verified while pending. No reviewed project task was executed.

The manager is local-only and user-started, with no login registration. The first
semantic request after a service restart still loads the configured models. Basic
review and lexical search need neither model. Adding another project requires an
explicit root configuration; the app does not silently allowlist model text.


Further invocation/context optimizations: [second speed pass](speed-pass-2.md).
