import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
const root=process.cwd(), bundle=path.join(root,'services/agent-bridge/gemini-cli/node_modules/@google/gemini-cli/bundle');
process.env.GEMINI_CLI_HOME=path.join(root,'run/gemini-home');
const {Config,PolicyEngine}=await import(pathToFileURL(path.join(bundle,'chunk-LAR4JEC7.js')));
const dir=path.join(root,'run/agents/gemini');
fs.mkdirSync(dir,{recursive:true});
const config=new Config({sessionId:crypto.randomUUID(),targetDir:dir,cwd:dir,model:'auto',
  debugMode:false,interactive:false,coreTools:[],mainAgentTools:[],mcpServers:{},mcpEnabled:false,
  extensionsEnabled:false,enableHooks:false,skillsSupport:false,adminSkillsEnabled:false,
  useRipgrep:false,approvalMode:'default',telemetry:{enabled:false,logPrompts:false}});
const registry=await config.createToolRegistry();
const tools=registry.getFunctionDeclarations().map(tool=>tool.name);
const engine=new PolicyEngine({rules:[{toolName:'*',decision:'deny',priority:5.999}],defaultDecision:'deny',nonInteractive:true});
const denied={};
for(const name of ['run_shell_command','read_file','write_file','web_fetch','unknown_future_tool']){
  const answer=await engine.check({name,args:{command:'fixture-only'}});
  denied[name]=answer.decision==='deny';
}
const artifact=path.join(bundle,'gemini.js');
const report={artifact_sha256:crypto.createHash('sha256').update(fs.readFileSync(artifact)).digest('hex'),
  policy_sha256:execFileSync(path.join(root,'.venv/Scripts/python.exe'),['-c',"from gobot.live_agents import policy_digest; print(policy_digest())"],{env:{...process.env,PYTHONPATH:path.join(root,'services/brain')},encoding:'utf8'}).trim(),
  tools,denied,mcp_enabled:false,extensions_enabled:false,hooks_enabled:false,real_model_requests:0,
  isolated:tools.length===0&&Object.values(denied).every(Boolean)};
const file=path.join(root,'run/agent-isolation.json');
const reports=fs.existsSync(file)?JSON.parse(fs.readFileSync(file,'utf8')):{};
reports.gemini=report;
fs.writeFileSync(file,JSON.stringify(reports,null,2));
console.log(JSON.stringify({gemini_offline_audit:report},null,2));
