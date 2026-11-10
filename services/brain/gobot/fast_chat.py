"""Direct Gemini API is retired by OWNER DIRECT. No network calls are permitted here."""
from .processes import AgentError
async def gemini_stream(*args,**kwargs):
    if False:yield ""
    raise AgentError("direct_gemini_api_disabled")
