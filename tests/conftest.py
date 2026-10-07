import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 테스트 세션 전체가 임시 DB를 쓰도록 settings 임포트 전에 경로를 고정합니다. 데모 DB는 건드리지 않습니다.
_SESSION_DB = Path(tempfile.mkdtemp(prefix="logiwise-test-")) / "session.db"
os.environ["LOGIWISE_DB_PATH"] = str(_SESSION_DB)

from logiwise import seed  # noqa: E402


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    seed.seed(path, force=True)
    return path


@pytest.fixture
def session_db():
    """app.py(AppTest)가 사용하는 세션 DB. 매번 재생성합니다."""
    seed.seed(_SESSION_DB, force=True)
    return _SESSION_DB
