import pytest
from gobot.config import Settings
@pytest.fixture
def settings(tmp_path):
    return Settings(db=str(tmp_path/'memory.sqlite'),api_token='a'*48,bridge_secret='b'*48)
