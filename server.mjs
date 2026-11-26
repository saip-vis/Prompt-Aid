import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { z } from 'zod';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { registerAppResource, registerAppTool, RESOURCE_MIME_TYPE } from '@modelcontextprotocol/ext-apps/server';

const WIDGET_URI = 'ui://prompt-aid/review.html';

export function createPromptAidServer() {
  const server = new McpServer({name:'prompt-aid', version:'0.1.0'});
  registerAppResource(server, 'prompt-review', WIDGET_URI, {}, async () => ({
    contents: [{uri:WIDGET_URI, mimeType:RESOURCE_MIME_TYPE, text:await readFile(new URL('./public/index.html', import.meta.url), 'utf8')}]
  }));
  registerAppTool(server, 'review_prompt', {
    title:'Review a coding prompt',
    description:'Display an interactive review card for a coding prompt. First draft a faithful improved prompt yourself; provide the original, improved text, and brief changes. This tool displays supplied text and does not call a model, edit code, or submit the prompt.',
    inputSchema: {
      original: z.string().min(1).max(12000).refine(s=>s.trim().length>0).describe('The user’s original prompt.'),
      improved: z.string().min(1).max(16000).refine(s=>s.trim().length>0).describe('A faithful draft improved prompt prepared by the assistant.'),
      changes: z.array(z.string().min(1).max(300)).max(6).default([]).describe('Brief descriptions of actual changes, not invented requirements.'),
      questions: z.array(z.string().min(1).max(300)).max(3).default([]).describe('Optional genuinely useful questions, clearly separate from the prompt.'),
      limitations: z.array(z.string().min(1).max(300)).max(3).default([]).describe('Relevant uncertainties about context or assistant capabilities, never presented as known facts.')
    },
    _meta: {ui: {resourceUri:WIDGET_URI}}
  }, async ({original, improved, changes, questions, limitations}) => ({
    content:[{type:'text',text:`Prompt Aid review ready. Original: ${original}\n\nImproved draft: ${improved}`}],
    structuredContent:{original, improved, changes, questions, limitations}
  }));
  return server;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const server = createPromptAidServer();
  await server.connect(new StdioServerTransport());
}
