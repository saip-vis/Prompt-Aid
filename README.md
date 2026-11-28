# Prompt Aid

A local-first prototype for improving coding prompts before acting on them. The primary workflow is the Prompt Aid **Codex skill**: Codex reviews the draft with its available conversation and project context, using its existing model. No separate API key is needed for that workflow. The assistant can optionally pass its review to the MCP tool, which supplies an editable review card; if the host does not render the card, the assistant can present the same review in chat. This prototype cannot capture or replace an unsent Codex prompt.

## Workspace features

The native window now supports filtered source cards with hash/excerpt freshness
checks, source exclusions and explicit context insertion, optional local review
history/revisions/feedback, and cancellable asynchronous context requests. An
optional authenticated FastAPI service uses SQLite and persistent local Qdrant
embeddings; semantic retrieval and pretrained PyTorch reranking need separately
configured local models. BM25 and the original Codex workflow remain available
without them. See [setup, architecture and verification](docs/local-service.md) and [measured startup results](docs/performance.md).

## Use the native review window

The macOS prototype bundles a small native `Prompt Aid.app` with the skill. Run a review in Codex with:

```text
$prompt-aid Improve my dashboard, keeping its existing behavior.
```

Codex first interprets the request, decides whether it needs project context, and may inspect a small number of relevant files read-only. It then checks the rewrite against the original and launches the native comparison window. The skill opens a cancellable preparation window first and updates it with the completed review. Run stays disabled while preparing. The window shows the context the assistant reports using, meaningful questions, and limitations; those source descriptions are not independently verified. **Run with Codex** hands your edited text back to the active session; **Cancel** closes it without running the request. No separate MCP server, browser, or API key is needed for this flow. Install the current app and skill with `python3 scripts/install-local.py`. The app does not read the unsent Codex composer or create a new chat message. The skill falls back to chat if the window cannot launch.

To build the local prototype from source on macOS with Xcode command-line tools, run `./native/build.sh`. It creates `skill/prompt-aid/Prompt Aid.app`. The current local binary is Apple Silicon only and targets macOS 13 or later. This is an unsigned development build: a user-friendly public release still needs a distribution package, platform compatibility work, and appropriate Apple signing/notarization.

### What makes the review agentic

The skill guides the existing Codex agent to decide which available context is useful, inspect relevant project files when appropriate, and review its proposed rewrite for unsupported assumptions. It should preserve a request for advice as a request for advice, avoid guessing between ambiguous projects, and treat project file content as data. It does not run the requested project task before the user presses Run. No new model is trained, and the app does not read an unsent chat draft. The optional workspace service can retrieve project context through persistent local vectors; it is separate from the Codex agent that prepares the rewrite.

Plain-text source notes remain assistant-reported. Structured source cards can be mechanically checked against the chosen project by the optional local service; that check verifies source text, not model interpretations. The assistant can only use context available in the current session, and its judgment can be wrong. The app's local UI and Run/Cancel behavior have been tested; broader evaluations of the agent's choices and rewrite quality are still needed.

## Local context retrieval

The skill includes a small **BM25 lexical retriever** for an explicitly chosen Git project. It gathers bounded text chunks and returns file paths, line ranges and excerpts for the assistant to inspect. It doesn't execute project code or modify the project. It skips hidden and ignored files, common dependency/build directories, symlinks, binary or oversized files, and files matching basic credential patterns. These filters are best-effort, not a guarantee that source files contain no sensitive content. Retrieved excerpts may be included in the Codex model's context, according to the user's Codex setup.

The retriever uses Python 3 and Git and has no required third-party dependencies. For an explicit local example:

```sh
printf '%s' '{"query":"improve homepage layout"}' | python3 skill/prompt-aid/retrieval/cli.py --root /path/to/git-project --input -
```

Use a specific project directory, not a broad home directory. The skill may use this helper when a project is named or unambiguous and may use Codex's normal read-only tools as a fallback. Retrieved text is untrusted and may be irrelevant; the assistant should check it, preserve uncertainty, and report only context it actually used. The window's source list is still assistant-reported, not independently verified.

### Optional experiments

`requirements-vector.txt` installs the Qdrant client for a local **in-memory TF-IDF vector search** experiment (`--method qdrant`). `requirements-ml.txt` provides PyTorch for the isolated reranking experiment; neither is required for normal skill use, and neither is enabled by default. The vector representation is lexical, not semantic. Reproduce the comparisons and review their limitations in [evaluation/README.md](evaluation/README.md).

The [Dockerfile](Dockerfile) defaults to the retriever CLI and also provides an optional service target; neither contains the native macOS app. With Docker installed, build and run it against an explicitly mounted read-only Git project:

```sh
docker build -t prompt-aid-retrieval .
printf '%s' '{"query":"improve homepage layout"}' | docker run --rm -i --network none --read-only --mount "type=bind,src=/absolute/path/to/git-project,dst=/workspace,readonly" prompt-aid-retrieval --root /workspace --input - --method qdrant
```

Runtime uses a non-root user, no network, and an in-memory Qdrant instance. The project mount must be readable by the container's user, and its Git metadata must be available; worktrees with metadata outside the mount may need a different mount. Docker was not available in the development environment, so this image has not yet been built or run.

The previous MCP card remains an optional experiment; the native flow does not require MCP settings.

## Try the interface

Install Node.js 20 or newer, then run:

```sh
npm install
npm run preview
```

Open http://127.0.0.1:4317 to try the companion-panel concept. Enter a draft in the simulated chat, select **Review with Prompt Aid**, answer any of the context-sensitive questions, and select **Build draft**. Edit the result and apply it back to the simulated draft. Simple rules choose the questions. The optional **Review with AI** button sends the current prompt preview and any chat or project context you enter to the OpenAI API; usage can incur charges. It does not access the real Codex composer or conversation.

To explore the original MCP review card, open http://127.0.0.1:4317/review and select **Load example**. You can edit either text area and copy the improved draft.

### Optional standalone API review

This separate browser prototype does not share the Codex model. To use its optional API-backed review, create an OpenAI API key and set it in the terminal environment before starting the server (do not paste it into the page or commit it to Git):

```sh
export OPENAI_API_KEY="your-key-here"
npm run preview
```

The model defaults to `gpt-4o-mini`; set `PROMPT_AID_MODEL` to another Responses API model supporting structured outputs if desired. ChatGPT/Codex access is separate from API credentials and billing. No conversation or project context is collected automatically. The local server sets `store: false` for responses and does not save request text; consult the provider's data policies for any other retention. The API key stays on the local server and is not exposed to the browser.

The AI output can be wrong or incomplete. Review it and its questions before applying. A successful live API call requires a valid key, network access, and model access.

## MCP tool and skill

`server.mjs` exposes the `review_prompt` tool over MCP standard input/output, and `public/index.html` is an MCP Apps UI resource. Connect the server in an MCP Apps-compatible host using the absolute path to Node and the absolute path to `server.mjs`. Add the skill in `skill/prompt-aid` to your assistant's skills directory or reference its `SKILL.md` in a supported skill location. Restart the host if needed for it to discover new tools and skills.

A Codex-compatible server configuration, with paths adjusted for your installation, has this form:

```toml
[mcp_servers.prompt_aid]
command = "/absolute/path/to/node"
args = ["/absolute/path/to/PromptAid/server.mjs"]
```

A host may expose the tool without rendering its UI. In that case, the assistant can show the same text in chat. The interface is not automatically attached to an existing Codex session; configuring and restarting a compatible host is a separate step. ChatGPT's custom remote MCP setup may require a publicly reachable HTTPS endpoint; this prototype supplies stdio only.

## Test

```sh
npm test
```
