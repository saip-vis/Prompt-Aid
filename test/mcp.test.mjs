import {test} from 'node:test';
import assert from 'node:assert/strict';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
import {fileURLToPath} from 'node:url';

test('MCP server exposes a review card and preserves the assistant’s draft',async()=>{
  const client=new Client({name:'prompt-aid-test',version:'1.0.0'});
  const transport=new StdioClientTransport({command:process.execPath,args:[fileURLToPath(new URL('../server.mjs',import.meta.url))],stderr:'pipe'});
  try{
    await client.connect(transport);
    const {tools}=await client.listTools();
    const tool=tools.find(t=>t.name==='review_prompt');
    assert.ok(tool);assert.equal(tool._meta.ui.resourceUri,'ui://prompt-aid/review.html');
    const resource=await client.readResource({uri:tool._meta.ui.resourceUri});
    assert.equal(resource.contents[0].mimeType,'text/html;profile=mcp-app');
    assert.match(resource.contents[0].text,/ui\/notifications\/tool-result/);
    const input={original:'  Keep the existing login.\n',improved:'Improve the login screen while preserving its behavior.',changes:['Preserved existing behavior.'],questions:[],limitations:['Only the supplied context was reviewed.']};
    const result=await client.callTool({name:'review_prompt',arguments:input});
    assert.equal(result.isError,undefined);
    assert.deepEqual(result.structuredContent,input);
    const legacy=await client.callTool({name:'review_prompt',arguments:{original:'A',improved:'B'}});
    assert.deepEqual(legacy.structuredContent.limitations,[],'limitations remain optional');
    const invalid=await client.callTool({name:'review_prompt',arguments:{...input,original:''}});
    assert.equal(invalid.isError,true,'empty input is rejected');
  } finally {await client.close();}
});
