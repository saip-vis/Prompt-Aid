# Local workspace features

Prompt Aid keeps its original Codex-driven rewrite flow. The optional workspace
service adds retrieval, source verification, explicit local saving and feedback.
It does **not** invoke a model API or rewrite the prompt by itself.

## Start the service

From this repository:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-service.txt
.venv/bin/python -m backend.manage start --root /absolute/path/to/git-project
```

Repeat `--root` to allow more projects. A request cannot choose another root.
The default binding is `127.0.0.1:4318`. The default data directory is
`~/.local/share/prompt-aid`; it contains SQLite, an automatically generated
0600 `api-token` file, and optional local vectors. Use `--data` to choose another
private directory. Do not share the token or include it in model prompts.

The manager starts or reuses one local background service and writes private
`connection.json` and `runtime.json` descriptors beside the database. The native
app discovers the connection without extra launch environment variables. Its
**Start / reconnect workspace** button can restart this configuration only for a
previously allowlisted project. No login-start registration is added. Stop it with:

```sh
.venv/bin/python -m backend.manage status
.venv/bin/python -m backend.manage stop
```

Repeat `--root` during initial setup to allow more projects. To change roots or
models, stop the current service and start it with the complete new configuration.
The button does not silently add roots from model-authored review text. The app
continues working without a service. Direct foreground `python -m backend.app`
remains available; stop that mode with Ctrl-C. Saved prompts and filtered source text persist locally; saving a review
is explicit. Deleting the data directory after stopping the service removes its
history and indexes. Normal reviews without this service remain ephemeral.

## Native app integration

Build with `./native/build.sh`. The app still takes a private review JSON path.
Existing review JSON is compatible. Add `projectRoot` only for the user's
explicitly chosen Git project, and optionally `sources` and `assumptions`:

```json
{
  "original": "Fix returning-user login",
  "improved": "Investigate returning-user login and fix the identified session issue.",
  "changes": ["Clarified the behavior to investigate."],
  "questions": [],
  "limitations": [],
  "evidence": [],
  "projectRoot": "/absolute/path/to/git-project",
  "sources": [],
  "assumptions": []
}
```

Launch from the skill session with service configuration in the environment,
not inside model-authored review text:

```sh
PROMPT_AID_SERVICE_URL=http://127.0.0.1:4318 \
PROMPT_AID_TOKEN_FILE="$HOME/.local/share/prompt-aid/api-token" \
"skill/prompt-aid/Prompt Aid.app/Contents/MacOS/PromptAid" /private/path/review.json
```

`Find context` refreshes the project index and searches using the current original
request. Choose Lexical, Hybrid or Semantic; Rerank is independently optional.
Operations run asynchronously and Stop cancels the client's pending request.
An indexing request already running in the service may still finish its local
cache transaction. Cancel always closes the review without running its prompt.

Expand source cards to inspect excerpts, line ranges and hashes. Exclude paths
using their checkboxes. `Insert selected context` rechecks freshness and inserts
only verified selected excerpts into the editable prompt. It does not regenerate
or silently change requirements. `Reset exclusions` lets you search excluded
paths again. Retrieved content must still be treated as untrusted source text.

`Save review` creates an immutable revision. Saving again links a new revision to
the previous saved one. History restores the saved suggestion and sources;
the original current request stays visible, and source freshness is rechecked.
`Useful`/`Not useful` stores explicit feedback without running anything. Useful
feedback includes the edited draft when it differs from the saved version.
Run returns exactly the currently edited prompt; it does not silently save it.

## Source evidence versus model claims

A source has `path`, `line_start`, `line_end`, `content_hash` (SHA-256 of the
whole file), `excerpt`, optional `excerpt_truncated`, `score` and `claim`.
Copy fields from actual retriever output. Never invent a hash, excerpt, or status.

The native app discards verification statuses supplied in initial review JSON.
Only a successful local service check sets its current source status:

- **verified**: the file hash, line range and excerpt match current filtered code;
- **stale**: the file is available but its content/range no longer matches;
- **unavailable**: the source is absent, outside the filtered scan, or excluded by
  current access/ignore/sensitive-content rules.

This verifies source text, not the truth of the model's `claim`. Model
interpretations and assumptions are labeled separately. The MCP browser card can
display excerpts but explicitly labels them as unverified in that card.

## Semantic retrieval and PyTorch reranking

BM25 needs no optional model packages. Install semantic dependencies separately:

```sh
.venv/bin/python -m pip install -r requirements-semantic.txt
```

Obtain a SentenceTransformer embedding model and, optionally, a CrossEncoder
reranker from a trusted provider, saving complete model directories locally.
Models used for the development check were `sentence-transformers/all-MiniLM-L6-v2`
and `cross-encoder/ms-marco-MiniLM-L6-v2`. They are small general-text baselines,
not code-specialized models or a newly trained Prompt Aid model.

```sh
HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
.venv/bin/python -m backend.manage start \
  --root /absolute/path/to/git-project \
  --embedding-model /absolute/path/to/embedding-model \
  --reranker-model /absolute/path/to/reranker-model
```

Inference uses local files only, CPU PyTorch and `trust_remote_code=False`. The
service never downloads model weights. Model content fingerprints isolate
collections when weights/configuration change. Model fingerprinting/loading is
lazy: `/health`, basic review and lexical search do not import PyTorch or load
weights. The first semantic/reranked search pays that cost; later searches reuse
the loaded models. Health distinguishes configured from loaded capabilities.
Qdrant local mode persists vectors
and only embeds missing/changed chunks. The service keeps a single Qdrant client
open until shutdown. Search responses include `vector_sync` counts (embedded,
reused, removed) and `timings` for indexing, dense retrieval and model loading.
The native status displays the synchronization counts. Deleted/ignored/sensitive chunks are
removed when that project's semantic index is next synchronized. Lexical search
refreshes SQLite before every query and never serves excluded stale text.

Hybrid ranking uses reciprocal rank fusion of BM25 and dense candidates. The
default cosine cutoff is 0.25 (the foreground `backend.app` exposes
`--semantic-threshold`); calibrate it on held-out
cases. Scores are not confidence probabilities. Hybrid without a configured
embedding model explicitly falls back to BM25 with a warning; Semantic instead
returns an error. Missing reranking warns and retains the existing order.
The old `cli.py --method qdrant` remains a separate TF-IDF experiment.

The scanner rechecks all bounded eligible files for freshness. Incrementality
means unchanged database rows/embeddings are reused, not that unchanged files
avoid disk reads. Chunking remains bounded 30-line blocks. Current Git ignore
rules, symlink exclusions and best-effort secret filters apply on every refresh.
These filters do not guarantee removal of every possible sensitive string.

## API and MCP

All HTTP routes require `Authorization: Bearer <private token>`. Browser Origin
requests are rejected; this is a local native/CLI service, not a public web API.
Bodies are bounded to 128 KB and validation errors omit submitted input values.
No request-body, prompt, source or token logging is added. Search reports its
method, model fingerprints, warnings and elapsed time.

| Route | Purpose |
|---|---|
| `GET /health` | Available local capabilities |
| `GET /projects` | Configured indexed projects |
| `POST /projects/index` | Refresh an explicit root |
| `POST /context/search` | Search a project, with exclusions and optional reranking |
| `POST /sources/verify` | Recheck source text |
| `POST /reviews` | Save a revision, optionally with `parent_id` |
| `GET /reviews?project_id=...` | Bounded history summaries |
| `GET /reviews/{id}` | Read/export a full saved review |
| `POST /reviews/{id}/feedback` | Record accepted, edited or rejected feedback |

The stdio MCP server now exposes `index_project`, `retrieve_context`, and
`review_history` in addition to `review_prompt`. To enable workspace tools,
configure the server environment explicitly (paths shown as examples):

```toml
[mcp_servers.prompt_aid.env]
PROMPT_AID_PROJECT_ROOTS = '["/absolute/path/to/git-project"]'
PROMPT_AID_PYTHON = "/absolute/path/to/PromptAid/.venv/bin/python"
PROMPT_AID_DATA = "/private/path/to/prompt-aid-mcp-data"
# Optional already-downloaded local model directories:
# PROMPT_AID_EMBEDDING_MODEL = "/absolute/path/to/embedding-model"
# PROMPT_AID_RERANKER_MODEL = "/absolute/path/to/reranker-model"
```

The MCP bridge runs a bounded Python JSON subprocess without a shell. With a
manager-created `connection.json` in `PROMPT_AID_DATA`, it sends authenticated
loopback requests to the already-running owner; native and MCP calls reuse the
same loaded models and vectors. Keep `PROMPT_AID_DATA` equal to the manager's
`--data` directory for this mode. An offline configured service produces a clear
reconnect error instead of silently opening a competing database owner.

Without a connection descriptor the bridge still supports standalone operation.
Use a separate data directory if combining standalone mode with a direct
foreground service: Qdrant local storage allows one process owner. Review/source
data stays local unless the assistant includes retrieved excerpts in its model
context.

## Verification and evaluation

```sh
npm test
.venv/bin/python -m unittest discover -s test -p 'test_*.py' -v
swift test
./native/build.sh
HF_HUB_OFFLINE=1 PROMPT_AID_TEST_EMBEDDING_MODEL=/path/to/embedding-model \
PROMPT_AID_TEST_RERANKER_MODEL=/path/to/reranker-model \
.venv/bin/python -m unittest discover -s test -p test_semantic.py -v
```

See [retrieval evaluation](../evaluation/README.md) for paired retrieval methods
and human-labeled rewrite evaluation. Default tests don't download models or
call a paid API. CI runs Node, Python, Swift and container checks. A workflow file
is not evidence that remote CI has run; check the actual run before claiming it.

## Containers

The default Docker target keeps the existing offline retriever CLI. The service
is a separate target:

```sh
docker build --target service -t prompt-aid-service .
docker volume create prompt-aid-data
docker run --rm -p 127.0.0.1:4318:4318 \
  --mount type=bind,src=/absolute/path/to/git-project,dst=/workspace,readonly \
  --mount type=volume,src=prompt-aid-data,dst=/data prompt-aid-service
```

The container binds all interfaces *inside the container*; publish only to host
loopback as above. It runs as UID 10001, so mounted files must be readable by that
user. Get the token from the private data volume when configuring a client.
Semantic dependencies/models are not bundled in this base image. Use the local
Python service for the verified semantic setup. No cloud deployment is required.
Docker is unavailable on the development machine, so local image execution is
unverified; CI includes a build and offline retriever smoke check.


## Early review window and local installation

The native app accepts `pending: true` with an empty `improved` field. The skill
opens this window first, prepares the review read-only, then atomically replaces
the private payload with a final review. Original request and project root must
match. Run stays disabled until the update is valid; Cancel works throughout.
The final draft is editable and Run returns exactly that text without executing it
inside the app. No configured service is needed for this path.

```sh
python3 scripts/install-local.py
```

This builds an optimized native app and copies the skill, app and retrieval helpers
to `~/.codex/skills/prompt-aid`. Existing installation files are backed up privately
to a temporary directory. Models, databases and credentials are never copied into
the skill. The manager's private runtime descriptor points back to this checkout
and its Python environment; rerun setup after moving either.

For content-free native timing, set `PROMPT_AID_LAUNCH_METRICS` to a private output
file. Events include `window_ready_ms` and, for the pending path,
`review_ready_ms`. They measure native process time, not provider latency before
the process starts. No prompts, sources or credentials are recorded.
See [measured launch and persistence results](performance.md).


## Single-scan context and the fast skill launcher

`POST /context/search` now accepts exactly one of `project_id` or an explicitly
allowed `root`; passing both/neither is rejected. It refreshes once and returns
`project_id` plus source snapshots generated from that filtered scan. The native
app no longer repeats automatic verification immediately after that response;
**Verify sources**, **Insert selected context**, saving and history restoration
still recheck freshness.

The skill's first tool action uses `review.py open`, reading a JSON object with
`original` and optional `projectRoot` on stdin. It yields a `review_starting` event
and private `review_file`, then waits for the app result. Publish the final JSON
with `review.py publish --review-file <path>`; the helper enforces the unchanged
original/project and cleans up after the app exits. Optional `--metrics <path>`
retains content-free native timing. A starting event is not proof of window
readiness or user approval.

One-off review context defaults to `retrieval/cli.py --root <project> --input -
--limit 3`; it avoids service/model setup. `review.py context --workspace` accepts
`root` and `query` on stdin and optionally reuses an already configured workspace.
Both paths are bounded and local-only. See [the second speed pass](speed-pass-2.md)
for actual measurements and limits.
