"""Root pytest conftest — load .env before all tests."""
import inspect
import pathlib
import time

import pytest
from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).parent / ".env", override=True)

_INTEGRATION_DIR = str(pathlib.Path(__file__).parent / "tests" / "integration")


@pytest.fixture(autouse=True)
def _inter_test_cooldown(request):
    """5-second cooldown *after* each async integration test.

    Prevents APIM from throttling the MCP beta endpoint when the full
    integration suite runs sequentially in a single pytest session.
    Unit tests (sync functions) are unaffected.
    """
    yield
    node_path = str(request.node.fspath)
    is_integration = _INTEGRATION_DIR in node_path
    is_async = inspect.iscoroutinefunction(request.node.function)
    if is_integration and is_async:
        time.sleep(5)
