import asyncio
import aiohttp
import pytest
from core.ai_service import YandexGPTConfig, YandexGPTService

class MockResponse:
    def __init__(self, status, data):
        self.status = status
        self._data = data

    async def json(self):
        return self._data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass


class MockRequestContextManager:
    def __init__(self, response):
        self.response = response

    def __await__(self):
        async def _inner():
            return self.response

        return _inner().__await__()

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, exc_type, exc, tb):
        pass


@pytest.mark.asyncio
async def test_get_completion_retries(monkeypatch):
    attempts = 0

    def mock_post(self, url, *, json=None, headers=None, timeout=None):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise aiohttp.ClientError("boom")
        response = MockResponse(200, {"result": {"alternatives": [{"message": {"text": "ok"}}], "usage": {}}})
        return MockRequestContextManager(response)

    monkeypatch.setattr(aiohttp.ClientSession, "post", mock_post)

    config = YandexGPTConfig(
        api_key="key",
        folder_id="folder",
        retries=3,
        retry_delay=0,
        timeout=5,
    )

    async with YandexGPTService(config) as service:
        result = await service.get_completion("test")

    assert attempts == 3
    assert result["success"] is True
    assert result["text"] == "ok"
