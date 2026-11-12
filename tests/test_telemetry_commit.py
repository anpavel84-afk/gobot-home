"""The startup pin follows the loaded branch and survives later docs commits."""
import subprocess
from gobot import telemetry


def test_running_commit_uses_head_and_remains_pinned(tmp_path,monkeypatch):
    def git(*args):
        return subprocess.check_output(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
                                        *args],cwd=tmp_path,stderr=subprocess.DEVNULL).decode().strip()
    git('init','-q','--initial-branch=master')
    git('commit','-q','--allow-empty','-m','Base')
    base=git('rev-parse','HEAD')
    git('checkout','-q','-b','hardware-test')
    git('commit','-q','--allow-empty','-m','Loaded code')
    loaded=git('rev-parse','HEAD')
    monkeypatch.setattr(telemetry,'ROOT',tmp_path)
    telemetry.code_commit.cache_clear()
    try:
        assert loaded!=base and telemetry.code_commit()==loaded
        git('commit','-q','--allow-empty','-m','Later docs')
        assert git('rev-parse','HEAD')!=loaded
        assert telemetry.code_commit()==loaded
    finally:telemetry.code_commit.cache_clear()
