"""Official CLI transports. Admission depends on local isolation evidence and owner quota consent."""
import asyncio
from .telemetry import mark
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tomllib
from functools import lru_cache

from .agents import AppServerTransport, CodexAppServerAdapter, GeminiCLIAdapter
from .processes import AgentError, clean_environment, native_process

ROOT = Path(__file__).resolve().parents[3]
POLICIES = ROOT / "services/agent-bridge/policies"
WORK = ROOT / "run/agents"
GEMINI_PACKAGE = ROOT / "services/agent-bridge/gemini-cli/node_modules/@google/gemini-cli"

def digest(path):
    path=Path(path);info=path.stat()
    return _cached_digest(str(path),info.st_size,info.st_mtime_ns)
@lru_cache(maxsize=32)
def _cached_digest(path,size,modified):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def policy_digest():
    paths = [Path(__file__), ROOT / 'services/brain/gobot/agents.py',
             ROOT / 'services/brain/gobot/expert_profiles.py',
             ROOT / 'services/brain/gobot/processes.py', ROOT / 'services/brain/gobot/telemetry.py', POLICIES / 'gemini-settings.json',
             POLICIES / 'gemini-deny.toml']
    return hashlib.sha256(''.join(digest(p) for p in paths).encode()).hexdigest()

async def codex_account_present():
    argv, workspace, _ = codex_argv()
    async with native_process(argv, workspace) as process:
        rpc = AppServerTransport(process.stdout, process.stdin, timeout=10)
        await rpc.start()
        try:
            await CodexAppServerAdapter(rpc, workspace).initialize()
            answer = await rpc.request('account/read', {'refreshToken': False})
            return answer.get('account', {}).get('type') == 'chatgpt' if answer.get('account') else False
        finally:
            await rpc.close()

def codex_binary():
    shim = shutil.which("codex.cmd") or shutil.which("codex")
    if not shim:
        return None
    if Path(shim).suffix.lower() == ".exe":
        return Path(shim)
    packages = Path(shim).parent / "node_modules/@openai/codex"
    candidates = list(packages.glob("node_modules/@openai/codex-win32-x64/vendor/*/bin/codex.exe"))
    return candidates[0] if len(candidates) == 1 else None

def prepare_codex():
    executable = codex_binary()
    if not executable:
        raise AgentError("codex_not_installed")
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    cache = home / "models_cache.json"
    if not cache.exists():
        raise AgentError("codex_model_metadata_missing")
    models = json.loads(cache.read_text(encoding="utf-8"))["models"]
    for model in models:
        model["shell_type"] = "disabled"
        model["apply_patch_tool_type"] = None
        model["experimental_supported_tools"] = []
        model["include_skills_usage_instructions"] = False
        model["include_plugin_usage_instructions"] = False
        model["include_apps_usage_instructions"] = False
    workspace = WORK / "codex"
    workspace.mkdir(parents=True, exist_ok=True)
    catalog = WORK / "codex-text-only-models.json"
    catalog.write_text(json.dumps({"models": models}), encoding="utf-8")
    config = {
        "sandbox_mode": "read-only", "approval_policy": "on-request", "web_search": "disabled",
        "model_catalog_json": str(catalog), "project_doc_max_bytes": 0,
        "skills": {"bundled": {"enabled": False}, "include_instructions": False},
        "tools": {"update_plan": {"enabled": False}}, "notify": [],
        "history": {"persistence": "none"}, "mcp_servers": {},
    }
    schema = json.loads((ROOT / "vendor/references/live-agents/config.schema.json").read_text())
    def boolean_feature(value):
        if value.get("type") == "boolean":
            return True
        reference = value.get("$ref", "").split("/")[-1]
        definition = schema.get("definitions", {}).get(reference, {})
        return any(item.get("type") == "boolean" for item in definition.get("anyOf", []))
    config["features"] = {name: False for name, value in schema["properties"]["features"]["properties"].items()
                          if "." not in name and boolean_feature(value)}
    config["features"]["skip_host_skill_discovery"] = True
    user_config = home / "config.toml"
    if user_config.exists():
        # Read configuration metadata only; never copy or output auth values.
        parsed = tomllib.loads(user_config.read_text(encoding="utf-8"))
        for name in parsed.get("mcp_servers", {}):
            # Each override must remain a valid server definition even though it is disabled.
            # A known harmless local command replaces any inherited remote transport or credentials.
            config["mcp_servers"][name] = {"command": sys.executable, "args": [], "enabled": False}
        preferred = parsed.get("model")
    else:
        preferred = None
    model = preferred if preferred in {m["slug"] for m in models} else sorted(models, key=lambda m: m.get("priority", 999))[0]["slug"]
    return executable, workspace, config, model

def codex_argv(extra=None):
    executable, workspace, config, model = prepare_codex()
    if extra:
        config.update(extra)
    # JSON is valid TOML for scalar values; dictionaries need explicit dotted-key assignments.
    def entries(prefix, value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield from entries(prefix + "." + key if prefix else key, item)
        else:
            yield prefix + "=" + json.dumps(value)
    argv = [str(executable)]
    for key, value in config.items():
        if key == "mcp_servers":
            argv += ["-c", "mcp_servers={}"]
            continue
        for item in entries(key, value):
            argv += ["-c", item]
    return argv + ["app-server", "--stdio"], workspace, model

def gemini_environment():
    env = clean_environment()
    home = ROOT / "run/gemini-home"
    (home / ".gemini").mkdir(parents=True, exist_ok=True)
    env.update({
        "GEMINI_CLI_HOME": str(home),
        "GEMINI_CLI_SYSTEM_SETTINGS_PATH": str(POLICIES / "gemini-settings.json"),
        "GEMINI_CLI_SYSTEM_DEFAULTS_PATH": str(POLICIES / "gemini-settings.json"),
        "GEMINI_TELEMETRY_ENABLED": "false", "GEMINI_TELEMETRY_LOG_PROMPTS": "false",
        "GOOGLE_GENAI_USE_GCA": "true", "NO_COLOR": "1",
    })
    return env

def context_prompt(text, context):
    # Neutralize CLI @file expansion before any headless preprocessing can read a file.
    from .context_manager import serialize_context
    return serialize_context(text,context)

class CodexLiveAdapter:
    def __init__(self):self.usage=None
    async def stream(self, text, context, *, extra_config=None,model_id=None):
        mark("argv_policy_start")
        argv, workspace, model = codex_argv(extra_config)
        mark("argv_policy_end")
        model=model_id or model
        async with native_process(argv, workspace) as process:
            rpc = AppServerTransport(process.stdout, process.stdin, timeout=15)
            await rpc.start()
            adapter = CodexAppServerAdapter(rpc, workspace)
            try:
                mark("provider_init_start")
                await adapter.initialize();mark("provider_initialized")
                result = await rpc.request("thread/start", {
                    "cwd": str(workspace), "model": model, "approvalPolicy": "on-request",
                    "sandbox": "read-only", "ephemeral": True,
                    "baseInstructions": "Ты домашний текстовый помощник. Инструменты недоступны.",
                })
                adapter.thread_id = result["thread"]["id"]
                context['_provider_session_id']=adapter.thread_id
                async for delta in adapter.stream(context_prompt(text, context)):
                    yield delta
                self.usage=adapter.usage
            finally:
                await rpc.close()

class GeminiLiveAdapter:
    """Retired by OWNER DIRECT; retained only as an explicit compatibility denial."""
    async def stream(self, text, context):
        if False:
            yield ""
        raise AgentError("gemini_cli_retired")


def agent_status(usage_consent=False):
    audit_path = ROOT / "run/agent-isolation.json"
    audits = json.loads(audit_path.read_text()) if audit_path.exists() else {}
    enabled_path = ROOT / "run/agent-consent.json"
    consent = json.loads(enabled_path.read_text()) if enabled_path.exists() else {}
    executable = codex_binary()
    script = GEMINI_PACKAGE / "bundle/gemini.js"
    statuses = {}
    access_path=ROOT/'run/gemini-eligibility.json'
    access=json.loads(access_path.read_text()) if access_path.exists() else {}
    credentials=ROOT/'run/gemini-home/.gemini/oauth_creds.json'
    blocked=access.get('reason') if credentials.exists() and access.get('credential_mtime_ns')==credentials.stat().st_mtime_ns else None
    for name, path, auth in [
        ("codex", executable, audits.get('codex', {}).get('oauth_authenticated', False)),
        ("gemini", script, (ROOT / "run/gemini-home/.gemini/oauth_creds.json").exists()),
    ]:
        evidence = audits.get(name, {})
        installed = bool(path and path.exists())
        isolated = installed and evidence.get("isolated") is True and evidence.get("artifact_sha256") == digest(path) and evidence.get("tools") == [] and evidence.get('policy_sha256') == policy_digest()
        quota = bool(usage_consent)
        reason = "not_installed" if not installed else "isolation_not_verified" if not isolated else "oauth_login_required" if not auth else blocked if name=='gemini' and blocked else "quota_consent_required" if not quota else None
        statuses[name] = {"installed": installed, "oauth_cached": auth, "isolation_verified": bool(isolated),
                          "quota_consent": quota, "available": reason is None, "reason": reason}
    statuses['gemini'].update({'available':False,'reason':'gemini_cli_retired'})
    from .antigravity import status as antigravity_status
    statuses['antigravity']=antigravity_status(usage_consent)
    return statuses

async def live_stream(provider, text, context, *, usage_consent=False,model_id=None,usage=None,antigravity_transport='stream_json',expert_profile=None):
    mark("bridge_admission_start")
    state = await asyncio.to_thread(agent_status,usage_consent)
    state = state.get(provider)
    mark("bridge_admission_end")
    if not state or not state["available"]:
        raise AgentError(state["reason"] if state else "unknown_provider")
    extra=None
    if expert_profile:
        from .expert_profiles import resolve_profile
        profile=resolve_profile(expert_profile)
        if not profile['metadata_verified'] or profile['provider']!=provider or profile['model']!=model_id:raise AgentError('expert_model_effort_unavailable')
        if provider=='codex':extra={'model_reasoning_effort':profile['effort']}
    if provider=='codex':adapter=CodexLiveAdapter()
    elif provider=='antigravity':
        if antigravity_transport=='acp_experimental':
            from .antigravity_acp import AntigravityACPAdapter
            adapter=AntigravityACPAdapter()
        elif antigravity_transport=='stream_json':
            from .antigravity import AntigravityAdapter
            adapter=AntigravityAdapter()
        else:raise AgentError('unsupported_antigravity_transport')
    else:raise AgentError('gemini_cli_retired' if provider=='gemini' else 'unknown_provider')
    async with asyncio.timeout(90):
        stream=adapter.stream(text,context,model_id=model_id,extra_config=extra) if extra else adapter.stream(text,context,model_id=model_id)
        async for delta in stream:
            yield delta
        if usage is not None and getattr(adapter,'usage',None):usage.update(adapter.usage)
