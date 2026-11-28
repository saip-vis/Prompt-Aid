# Faster invocation and context preparation

November 27, 2026. This pass focuses on the delay before launch, unnecessary host
work, and context preparation. It does not replace or speed up the host LLM.

## Invocation

The installed skill now requires the first tool action to run the stdlib-only
`review.py open` launcher. It allows only the brief acknowledgement required by
the host, with no plan or explanation before launch. The helper owns the private
payload, opens the pending window, prints the path once, and cleans up after
Run/Cancel. `review.py publish` validates and atomically updates that same window.
No permission bypass or model-compute allocation is possible through a skill.

The skill was shortened from 7,882 bytes to approximately 5.5 KB, avoids redundant
rewrites of already-clear requests, and uses conversation evidence first. When
project files are needed, one focused lexical query returns at most three chunks
by default. Larger/context-sensitive requests may still need additional reads;
explicit user requirements must always be preserved.

## Measured context preparation

Same frozen, filtered PromptAid source snapshot; same six distinct queries plus
three repeated queries per method; real local MiniLM embeddings for hybrid mode.
The legacy path represents the first context lookup of a fresh native review:
index, search (refresh), and verification. The new path is one root-scoped search
whose source text comes from its own fresh scan. Store, API and native return
boundaries were exercised separately. Provider/tool-transport latency is excluded.

| Per-review context operation | Before | After |
|---|---:|---:|
| Lexical, warm median | 209.07 ms | 63.78 ms |
| Hybrid, warm median | 307.10 ms | 99.91 ms |
| Lexical, first lookup | 206.59 ms | 87.49 ms |
| Hybrid, first lookup including model/index initialization | 9290.51 ms | 8158.55 ms |
| Filtered source scans | 3 | 1 |

Warm context preparation improved about 69% (lexical) and 67% (hybrid). All 18
ranked source lists were identical. Cold-model initialization remains expensive;
the first-query difference is not claimed as a reliable model-loading speedup.
Raw samples: `speed-pass-2.json` (local, generated measurement samples).

A separate benchmark compared the old one-off CLI with a service-aware helper.
The extra service path was slower, so it was not selected as the skill default.
The direct CLI remains the default, at roughly 0.13 seconds on this snapshot;
no significant speedup is claimed for that standalone scan. The optional helper
exists for repeated workspace use. The primary generation-side gains are less
unnecessary investigation, smaller default context, and shorter rewrite output.
These are workflow changes, not measured provider inference improvements.

## Implementation and checks

- Root-scoped search resolves/indexes once. The MCP bridge no longer indexes
  immediately before asking search to index again.
- BM25 token statistics are cached by the current corpus fingerprint; file edits,
  deletions, ignore rules and exclusions remain respected. File hashes are
  computed once per file rather than once per chunk.
- The exclusive Qdrant owner caches committed vector IDs, hydrates them on restart,
  and invalidates that cache after failed syncs. No warm full-collection scroll.
- CLI/MCP local HTTP calls avoid repeated health requests and unnecessary HTTPS
  handler setup. Loopback validation, private token checks, no proxies and no
  redirect following remain enforced.
- Native search accepts fresh server-generated source status. Explicit insertion,
  verification, saving and history restoration still recheck current files.
- Tests cover single-scan search, lexical cache invalidation, exact exclusions,
  root isolation, interrupted vector synchronization, atomic publishing, cleanup,
  HTTP restrictions and offline fallback, alongside the existing suites.

No host inference speedup or instant pre-LLM launch is promised. A host must still
schedule the initial tool call; actual review preparation varies with the chosen
model, available conversation, and needed project investigation. Native launch
measurements from the first pass remain in [performance.md](performance.md).

Installed-app verification: one-command pending launch, atomic in-place publish,
Hybrid search and repeated warm search (142 ms, 311 reused chunks, zero embedded)
passed. Adding current ignore rules immediately marked a formerly included
benchmark artifact unavailable on explicit verification. Generated raw timing
JSON is now ignored by retrieval; human-readable summaries remain available.
