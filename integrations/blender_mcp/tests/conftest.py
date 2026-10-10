import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # integrations/

from blender_mcp import worker_client  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "blender: needs a Blender executable (BLENDER_BIN or /Applications/Blender.app)")


@pytest.fixture(scope="session")
def blender_bin():
    b = worker_client.find_blender()
    if b is None:
        pytest.skip("Blender not available")
    return b
