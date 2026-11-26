# Prompt Aid

A local-first prototype for improving coding prompts before acting on them. The primary workflow is the Prompt Aid **Codex skill**: Codex reviews the draft with its available conversation and project context, using its existing model. No separate API key is needed for that workflow. The assistant can optionally pass its review to the MCP tool, which supplies an editable review card; if the host does not render the card, the assistant can present the same review in chat. This prototype cannot capture or replace an unsent Codex prompt.

## Use the native review window

The macOS prototype bundles a small native `Prompt Aid.app` with the skill. Run a review in Codex with:

```text
$prompt-aid Improve my dashboard, keeping its existing behavior.
```

Codex creates the review using available context and launches the native comparison window. **Run with Codex** hands your edited text back to the active session; **Cancel** closes it without running the request. No separate MCP server, browser, or API key is needed for this flow. The app does not read the unsent Codex composer or create a new chat message. The skill falls back to chat if the window cannot launch.

To build the local prototype from source on macOS with Xcode command-line tools, run `./native/build.sh`. It creates `skill/prompt-aid/Prompt Aid.app`. The current local binary is Apple Silicon only and targets macOS 13 or later. This is an unsigned development build: a user-friendly public release still needs a distribution package, platform compatibility work, and appropriate Apple signing/notarization.

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
