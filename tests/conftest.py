import pytest

from src.core.logging import setup_logging

setup_logging("DEBUG")


@pytest.fixture
def anyio_backend():
    return "asyncio"
