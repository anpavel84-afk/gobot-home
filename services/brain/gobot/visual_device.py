"""Future device renderer. No listener, OTA or JPEG WebSocket frames."""
from .presentation import esp32_projection

class ESP32VisualRenderer:
    def __init__(self,cache):self.cache=cache
    def render(self,frame):return esp32_projection(frame)
    def preview(self,frame,store,*,capabilities,user_tool_permission):
        if not user_tool_permission or 'self.screen.preview_image' not in capabilities:raise PermissionError('Confirmed user-only tool/capability required')
        if not frame.images or frame.metadata.state!='ready':raise ValueError('No ready image')
        data,_=self.cache.read(frame.images[0].asset_id,'device')
        url=store.add(data,ttl=30)
        return store.mcp_call(url,capabilities,user_tool_permission)
