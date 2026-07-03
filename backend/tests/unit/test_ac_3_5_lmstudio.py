"""Section 3.5: LM Studio detection and guidance. Contract-mock tier: the
real client against a fake transport, one case per guidance state."""

import httpx
import pytest

from meetingnotes.llm.client import LMStudioClient
from meetingnotes.llm.errors import LMStudioUnavailable


def client_with(handler) -> LMStudioClient:
    return LMStudioClient(http=httpx.Client(transport=httpx.MockTransport(handler)))


def unreachable(request):
    raise httpx.ConnectError("connection refused")


def no_model(request):
    assert request.url.path == "/api/v0/models", "the loaded-state endpoint, not /v1/models"
    return httpx.Response(200, json={"data": [
        {"id": "qwen3-30b", "state": "not-loaded"},
        {"id": "bge-m3", "state": "not-loaded"},
    ]})


def loaded(request):
    assert request.url.path == "/api/v0/models"
    return httpx.Response(200, json={"data": [
        {"id": "qwen3-30b", "state": "loaded"},
        {"id": "another-model", "state": "not-loaded"},
    ]})


def test_ac_3_5_a_lmstudio_guidance_states():
    """First run detects whether LM Studio is reachable with a model loaded
    and produces the right state for each case."""
    assert client_with(unreachable).status() == "unreachable"
    assert client_with(no_model).status() == "no_model_loaded"

    ready = client_with(loaded)
    assert ready.status() == "ready"
    # And the active model shown to the user is the loaded one only.
    models = ready.loaded_models()
    assert [m["id"] for m in models] == ["qwen3-30b"]

    with pytest.raises(LMStudioUnavailable):
        client_with(unreachable).loaded_models()
