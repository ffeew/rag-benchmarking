import hashlib
import math
from dataclasses import dataclass, field
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from rag_benchmarking.core.config import Settings, get_settings


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderMetadata:
    provider: str
    model: str | None
    raw: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatResult:
    content: str
    metadata: ProviderMetadata


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    metadata: ProviderMetadata


@dataclass(frozen=True)
class RerankResult:
    ranked_indices: list[int]
    scores: list[float]
    metadata: ProviderMetadata


def deterministic_embedding(text: str, dimension: int) -> list[float]:
    values: list[float] = []
    seed = text.encode("utf-8")
    counter = 0
    while len(values) < dimension:
        digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        for index in range(0, len(digest), 4):
            integer = int.from_bytes(digest[index : index + 4], "big", signed=False)
            values.append((integer / 2**32) * 2 - 1)
            if len(values) == dimension:
                break
        counter += 1
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / norm for value in values]


class OpenRouterClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = httpx.Client(
            base_url=self.settings.openrouter_base_url,
            timeout=self.settings.openrouter_timeout_seconds,
        )

    @property
    def enabled(self) -> bool:
        return bool(
            self.settings.openrouter_api_key
            and not self.settings.allow_mock_providers
            and self.settings.openrouter_chat_model
        )

    def _headers(self) -> dict[str, str]:
        api_key = self.settings.openrouter_api_key
        if api_key is None:
            raise ProviderError("OPENROUTER_API_KEY is not configured")
        headers = {
            "Authorization": f"Bearer {api_key.get_secret_value()}",
            "Content-Type": "application/json",
            "X-Title": self.settings.openrouter_app_name,
        }
        if self.settings.openrouter_site_url is not None:
            headers["HTTP-Referer"] = str(self.settings.openrouter_site_url)
        return headers

    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3))
    def chat(self, *, messages: list[dict[str, str]], model: str | None = None) -> ChatResult:
        selected_model = model or self.settings.openrouter_chat_model
        if not selected_model:
            raise ProviderError("OPENROUTER_CHAT_MODEL is not configured")
        if not self.enabled:
            content = "Mock provider mode is enabled; no upstream chat model was called."
            return ChatResult(
                content=content,
                metadata=ProviderMetadata(provider="mock-openrouter", model=selected_model),
            )
        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": messages,
            "provider": {"allow_fallbacks": True, "data_collection": "deny"},
        }
        response = self._client.post("/chat/completions", headers=self._headers(), json=payload)
        if response.status_code >= 400:
            raise ProviderError(f"OpenRouter chat failed: {response.status_code} {response.text[:500]}")
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return ChatResult(
            content=content,
            metadata=ProviderMetadata(
                provider="openrouter",
                model=data.get("model", selected_model),
                raw={"id": data.get("id"), "provider": data.get("provider")},
                usage=data.get("usage") or {},
            ),
        )

    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3))
    def embeddings(self, texts: list[str], model: str | None = None) -> EmbeddingResult:
        selected_model = model or self.settings.openrouter_embedding_model
        if not selected_model:
            raise ProviderError("OPENROUTER_EMBEDDING_MODEL is not configured")
        if not self.enabled:
            return EmbeddingResult(
                vectors=[deterministic_embedding(text, self.settings.embedding_dimension) for text in texts],
                metadata=ProviderMetadata(provider="mock-openrouter", model=selected_model),
            )
        response = self._client.post(
            "/embeddings",
            headers=self._headers(),
            json={
                "model": selected_model,
                "input": texts,
                "dimensions": self.settings.embedding_dimension,
            },
        )
        if response.status_code >= 400:
            raise ProviderError(f"OpenRouter embeddings failed: {response.status_code} {response.text[:500]}")
        data = response.json()
        vectors = [item["embedding"] for item in sorted(data["data"], key=lambda item: item["index"])]
        return EmbeddingResult(
            vectors=vectors,
            metadata=ProviderMetadata(
                provider="openrouter",
                model=data.get("model", selected_model),
                raw={"id": data.get("id")},
                usage=data.get("usage") or {},
            ),
        )

    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(2))
    def rerank(self, *, query: str, documents: list[str], model: str | None = None) -> RerankResult:
        selected_model = model or self.settings.openrouter_rerank_model
        if not selected_model:
            raise ProviderError("OPENROUTER_RERANK_MODEL is not configured")
        if not self.enabled:
            return RerankResult(
                ranked_indices=list(range(len(documents))),
                scores=[1.0 / (index + 1) for index in range(len(documents))],
                metadata=ProviderMetadata(provider="mock-openrouter", model=selected_model),
            )
        response = self._client.post(
            "/rerank",
            headers=self._headers(),
            json={"model": selected_model, "query": query, "documents": documents},
        )
        if response.status_code >= 400:
            raise ProviderError(f"OpenRouter rerank failed: {response.status_code} {response.text[:500]}")
        data = response.json()
        results = data.get("results", [])
        return RerankResult(
            ranked_indices=[int(item["index"]) for item in results],
            scores=[float(item.get("relevance_score", 0.0)) for item in results],
            metadata=ProviderMetadata(
                provider="openrouter",
                model=data.get("model", selected_model),
                raw={"id": data.get("id")},
                usage=data.get("usage") or {},
            ),
        )
