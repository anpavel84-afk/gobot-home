import json,subprocess
from pathlib import Path

def test_production_browser_native_lifecycle_without_providers():
    result=subprocess.run(['node','tests/realtime_browser.cjs'],cwd=Path(__file__).parents[1],capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    evidence=json.loads(result.stdout)
    assert evidence['native_session_reused'] and evidence['local_mic_cleanup']
    assert evidence['provider_calls']==0 and not evidence['provider_data_channel']
