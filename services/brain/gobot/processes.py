"""Native asyncio subprocesses with bounded output and kill-on-close Windows jobs."""
import asyncio
import os
from contextlib import asynccontextmanager

class AgentError(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code

def failure_code(value):
    """Classify technical errors into a fixed vocabulary, never return source text."""
    import json
    text=(value if isinstance(value,str) else json.dumps(value,default=str)).lower()
    groups=[('gemini_account_ineligible',['ineligibletiererror']),
            ('gemini_google_project_required',['google_cloud_project','project id is required']),
            ('agent_arguments_rejected',['unknown argument','unknown option','unrecognized argument','invalid value']),
            ('agent_quota_exceeded',['quota','rate limit','429']),
            ('agent_auth_required',['unauthorized','authentication','401','login required']),
            ('agent_model_unavailable',['model not found','model does not exist','model is not supported','not supported when using codex']),
            ('agent_access_denied',['403','permission denied','access denied']),
            ('agent_policy_denied',['sandbox','approval required','untrusted workspace']),
            ('agent_network_failed',['connection refused','network error','error sending request','timed out'])]
    for code,patterns in groups:
        if any(pattern in text for pattern in patterns):return code
    return 'agent_execution_failed'

class WindowsJob:
    def __init__(self, pid):
        self.handle = None
        if os.name != "nt":
            return
        import ctypes as c
        from ctypes import wintypes as w
        class Basic(c.Structure):
            _fields_ = [("process_time", c.c_int64), ("job_time", c.c_int64), ("flags", w.DWORD),
                        ("minimum", c.c_size_t), ("maximum", c.c_size_t), ("active", w.DWORD),
                        ("affinity", c.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]
        class Counters(c.Structure):
            _fields_ = [(name, c.c_uint64) for name in ["read", "write", "other", "read_bytes", "write_bytes", "other_bytes"]]
        class Extended(c.Structure):
            _fields_ = [("basic", Basic), ("io", Counters), ("process_memory", c.c_size_t),
                        ("job_memory", c.c_size_t), ("peak_process_memory", c.c_size_t), ("peak_job_memory", c.c_size_t)]
        kernel = c.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
        kernel.CreateJobObjectW.restype = w.HANDLE
        kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        kernel.OpenProcess.restype = w.HANDLE
        kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        kernel.CloseHandle.argtypes = [w.HANDLE]
        handle = kernel.CreateJobObjectW(None, None)
        if not handle:
            raise AgentError("windows_job_unavailable")
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        process = kernel.OpenProcess(0x0100 | 0x0001 | 0x1000, False, pid)
        try:
            if not kernel.SetInformationJobObject(handle, 9, c.byref(info), c.sizeof(info)) or not process or not kernel.AssignProcessToJobObject(handle, process):
                kernel.CloseHandle(handle)
                raise AgentError("windows_job_assignment_failed")
        finally:
            if process:
                kernel.CloseHandle(process)
        self.handle, self.kernel = handle, kernel

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

def clean_environment(source=None):
    source = source if source is not None else os.environ
    allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "USERPROFILE", "HOME", "HOMEDRIVE",
               "HOMEPATH", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "PROGRAMFILES", "PROGRAMFILES(X86)",
               "COMMONPROGRAMFILES", "COMSPEC", "LANG", "LC_ALL", "CODEX_HOME"}
    return {name: value for name, value in source.items() if name.upper() in allowed}

@asynccontextmanager
async def native_process(argv, cwd, env=None, discard_errors=True):
    options = {"creationflags": 0x08000000} if os.name == "nt" else {"start_new_session": True}
    process = await asyncio.create_subprocess_exec(
        *map(str, argv), cwd=str(cwd), env=env if env is not None else clean_environment(),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        limit=262144, **options)
    job = None
    process.gobot_failure=None
    async def discard_stderr():
        # Never log raw CLI stderr (may contain OAuth URLs, paths or provider errors).
        while chunk:=await process.stderr.read(4096):
            code=failure_code(chunk.decode(errors='replace'))
            if code!='agent_execution_failed':process.gobot_failure=code
    drain = asyncio.create_task(discard_stderr()) if discard_errors else None
    try:
        job = WindowsJob(process.pid)
        yield process
    finally:
        if job:
            job.close()
        if process.returncode is None:
            try:
                if os.name != "nt":
                    import signal
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(process.wait(), 3)
        except TimeoutError:
            process.kill()
            await process.wait()
        if drain:
            try:
                await asyncio.wait_for(drain, 2)
            except TimeoutError:
                drain.cancel()
                await asyncio.gather(drain, return_exceptions=True)
