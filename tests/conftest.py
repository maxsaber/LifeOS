"""
Pytest configuration and shared fixtures for LifeOS tests.

Test Categories:
- unit: Fast tests with no external dependencies (< 100ms each)
- slow: Tests requiring ChromaDB, sentence-transformers, or file watchers
- integration: Tests requiring running server or external APIs
- requires_ollama: Tests requiring Ollama LLM to be running
- requires_server: Tests requiring API server to be running

Run categories:
- pytest -m unit              # Fast unit tests only (~60s)
- pytest -m "not slow"        # Skip slow tests
- pytest -m "not integration" # Skip integration tests
- pytest                      # All tests
- pytest -n auto              # Parallel execution (requires pytest-xdist)
"""
import pytest
import os


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "unit: Fast unit tests")
    config.addinivalue_line("markers", "slow: Slow tests (ChromaDB, embeddings)")
    config.addinivalue_line("markers", "integration: Integration tests (server required)")
    config.addinivalue_line("markers", "requires_ollama: Requires Ollama running")
    config.addinivalue_line("markers", "requires_server: Requires API server running")


@pytest.fixture(scope="session")
def ollama_available():
    """Check if Ollama is available for tests."""
    try:
        import httpx
        response = httpx.get("http://localhost:11434", timeout=2.0)
        return response.status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="session")
def server_available():
    """Check if API server is available for tests."""
    try:
        import httpx
        response = httpx.get("http://localhost:8000/health", timeout=2.0)
        return response.status_code == 200
    except Exception:
        return False
