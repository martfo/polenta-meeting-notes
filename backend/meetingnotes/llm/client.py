"""The LM Studio client, OpenAI-compatible, on 127.0.0.1:1234.

No model name is hardcoded in requests, because LM Studio serves whatever
model is loaded regardless of the name field. To show the active model, read
/api/v0/models and filter for state == "loaded"; /v1/models is wrong for this
because it lists every downloaded model.
"""

from __future__ import annotations

from typing import Any

import httpx

from meetingnotes.llm.errors import LMStudioUnavailable

DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"


class LMStudioClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, http: httpx.Client | None = None,
                 timeout_s: float = 600.0):
        self.base_url = base_url.rstrip("/")
        self._http = http or httpx.Client(timeout=timeout_s)

    @property
    def _server_root(self) -> str:
        # http://127.0.0.1:1234/v1 -> http://127.0.0.1:1234
        return self.base_url.removesuffix("/v1")

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        payload: dict[str, Any] = {"messages": messages, "temperature": temperature}
        try:
            response = self._http.post(f"{self.base_url}/chat/completions", json=payload)
        except httpx.TransportError as exc:
            raise LMStudioUnavailable(f"LM Studio is not reachable: {exc}") from exc
        if response.status_code >= 500:
            raise LMStudioUnavailable(f"LM Studio returned {response.status_code}")
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def loaded_models(self) -> list[dict[str, Any]]:
        try:
            response = self._http.get(f"{self._server_root}/api/v0/models")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LMStudioUnavailable(f"LM Studio is not reachable: {exc}") from exc
        models = response.json().get("data", [])
        return [m for m in models if m.get("state") == "loaded"]

    def status(self) -> str:
        """One of: unreachable, no_model_loaded, ready. Drives the first-run
        guidance and the summary-pending state."""
        try:
            loaded = self.loaded_models()
        except LMStudioUnavailable:
            return "unreachable"
        return "ready" if loaded else "no_model_loaded"
