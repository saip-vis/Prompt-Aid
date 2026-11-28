# Prompt Aid local TypeScript client

For a Node.js/desktop integration with the authenticated Python service:

```ts
import {PromptAidClient} from './client.js';

// Read these from the owned private connection/token files in your local host.
const client = new PromptAidClient(localServiceURL, privateToken);
const {builds} = await client.listBuilds();
const run = await client.getBuild(builds[0].id);
const evidence = await client.comparison(run.id);
const updates = await client.events(run.id, 0);
```

`startBuild` requires an explicitly approved specification; `recheck` requires
explicit approval, and neither is implied by listing or replay. `stop` cancels the
owned work. Starting/checking operations run as existing Python background jobs.
The client does not start a daemon, load models, persist tokens, send emails or
connect to external hosts. Keep tokens in the local host; the service rejects
browser-origin requests, so this is not a browser frontend SDK.

Run `npm run test:sdk` to type-check the source and exercise transport/approval
rules. Output and `.d.ts` declarations are generated under ignored `.build/typescript`.
