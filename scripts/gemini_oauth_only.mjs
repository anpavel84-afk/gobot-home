// Pinned official 0.67.0 auth helper. No model/client inference is initialized.
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';
const root=process.cwd();
const {Config,getOauthClient}=await import(pathToFileURL(path.join(root,'services/agent-bridge/gemini-cli/node_modules/@google/gemini-cli/bundle/chunk-LAR4JEC7.js')));
const dir=path.join(root,'run/agents/gemini');
const config=new Config({sessionId:crypto.randomUUID(),targetDir:dir,cwd:dir,model:'auto',
  interactive:true,noBrowser:true,coreTools:[],mainAgentTools:[],mcpServers:{},mcpEnabled:false,
  extensionsEnabled:false,enableHooks:false,skillsSupport:false,adminSkillsEnabled:false,
  telemetry:{enabled:false,logPrompts:false}});
try {
  await getOauthClient('oauth-personal',config);
  // Official cacheCredentials is registered by the official client; never export tokens here.
  await new Promise(resolve=>setTimeout(resolve,200));
  process.stdout.write('\nGOBOT_OFFICIAL_OAUTH_OK\n');
  process.exitCode=0;
} catch (_) {
  process.stdout.write('\nGOBOT_OFFICIAL_OAUTH_FAILED\n');
  process.exitCode=1;
}
