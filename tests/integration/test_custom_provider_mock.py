import httpx

from softnix_agentic_agent.providers.openai_compatible_provider import OpenAICompatibleProvider


class DummyResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_custom_provider_generate(monkeypatch) -> None:
    def fake_post(url, headers, json, timeout):  # type: ignore[no-untyped-def]
        assert url.endswith("/chat/completions")
        return DummyResponse(
            {
                "choices": [{"message": {"content": "hello"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            }
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    p = OpenAICompatibleProvider(api_key="k", base_url="http://localhost:9999/v1")
    r = p.generate(messages=[{"role": "user", "content": "hi"}], model="x")
    assert r.content == "hello"
    assert r.usage["total_tokens"] == 3
