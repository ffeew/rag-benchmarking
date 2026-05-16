from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from rag_common.config import Settings, get_settings
from rag_common.providers.openrouter import ChatResult, ProviderError, ProviderMetadata


class ZaiClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = httpx.Client(
            base_url=self.settings.zai_base_url,
            timeout=self.settings.zai_timeout_seconds,
        )

    @property
    def enabled(self) -> bool:
        return bool(
            self.settings.zai_api_key
            and not self.settings.allow_mock_providers
            and self.settings.zai_chat_model
        )

    def _headers(self) -> dict[str, str]:
        api_key = self.settings.zai_api_key
        if api_key is None:
            raise ProviderError("ZAI_API_KEY is not configured")
        return {
            "Authorization": f"Bearer {api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }

    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3))
    def chat(self, *, messages: list[dict[str, str]], model: str | None = None) -> ChatResult:
        selected_model = model or self.settings.zai_chat_model
        if not selected_model:
            raise ProviderError("ZAI_CHAT_MODEL is not configured")
        if not self.enabled:
            content = "Mock provider mode is enabled; no upstream chat model was called."
            return ChatResult(
                content=content,
                metadata=ProviderMetadata(provider="mock-zai", model=selected_model),
            )
        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": messages,
        }
        if self.settings.eval_temperature_zero:
            payload["temperature"] = 0
        response = self._client.post("/chat/completions", headers=self._headers(), json=payload)
        if response.status_code >= 400:
            raise ProviderError(f"Z.AI chat failed: {response.status_code} {response.text[:500]}")
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return ChatResult(
            content=content,
            metadata=ProviderMetadata(
                provider="zai",
                model=data.get("model", selected_model),
                raw={"id": data.get("id")},
                usage=data.get("usage") or {},
            ),
        )
