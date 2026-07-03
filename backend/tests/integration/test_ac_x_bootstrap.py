"""AC-X-c: bootstrap. The app launches and health-checks the backend, and
the backend reports LM Studio reachable or gives a clear state when it is
not. The health-check logic runs here against fakes; the real model download
is a live-smoke."""

import httpx
from fastapi.testclient import TestClient

from meetingnotes.api.app import AppState, create_app
from meetingnotes.config import default_config
from meetingnotes.enrolment.gallery import Gallery
from meetingnotes.jobs.worker import Worker
from meetingnotes.llm.client import LMStudioClient


def make_app(conn, vault, stages, lm_handler):
    lm_client = LMStudioClient(http=httpx.Client(transport=httpx.MockTransport(lm_handler)))
    state = AppState(
        conn=conn, vault=vault, config=default_config(vault.root),
        worker=Worker(conn, stages), lm_client=lm_client,
        gallery=Gallery(conn, vault),
    )
    return create_app(state)


def test_ac_x_c_bootstrap_healthcheck(conn, vault, stages):
    """The health endpoint the supervisor polls: backend up, LM Studio state
    reported plainly for each case."""

    def lm_ready(request):
        return httpx.Response(200, json={"data": [{"id": "qwen", "state": "loaded"}]})

    def lm_down(request):
        raise httpx.ConnectError("connection refused")

    with TestClient(make_app(conn, vault, stages, lm_ready)) as client:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["lmstudio"] == "ready"
        assert body["queued_jobs"] == 0

    with TestClient(make_app(conn, vault, stages, lm_down)) as client:
        body = client.get("/health").json()
        assert body["status"] == "ok", "the backend itself is healthy"
        assert body["lmstudio"] == "unreachable", "a clear message, not a crash"
