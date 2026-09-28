import asyncio
from typing import Any

import httpx

from agent_sample.application.a2a.server import build_server
from agent_sample.application.service import ClassificationService, ClassifyOptions
from agent_sample.infrastructure.model.unconfigured import UnconfiguredGateway
from tests.fakes import ScriptedGateway, composition


def _service(gateway: Any) -> ClassificationService:
    return ClassificationService(composition(gateway).build, ClassifyOptions())


def _send(service: ClassificationService, text: str, metadata: dict[str, str]) -> dict[str, Any]:
    async def send() -> dict[str, Any]:
        app = build_server(service, "http://test")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/",
                headers={"A2A-Version": "1.0"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "SendMessage",
                    "params": {
                        "message": {
                            "messageId": "m-1",
                            "role": "ROLE_USER",
                            "parts": [{"text": text}],
                        },
                        "metadata": metadata,
                    },
                },
            )
        assert response.status_code == 200
        return response.json()["result"]["task"]

    return asyncio.run(send())


def test_a2a_classifies_with_the_server_default() -> None:
    task = _send(_service(UnconfiguredGateway("no key")), "Fui cobrado duas vezes", {})
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    text = task["artifacts"][0]["parts"][0]["text"]
    assert text.startswith("billing")
    assert "decided_by: workflow:sequential" in text


def test_a2a_accepts_the_strategy_per_request() -> None:
    metadata = {"strategy": "agent", "agent": "deepagents", "prompt_version": "v1"}
    task = _send(_service(ScriptedGateway("sales")), "Fui cobrado duas vezes", metadata)
    text = task["artifacts"][0]["parts"][0]["text"]
    assert text.startswith("sales")
    assert "prompt=classify_subject@v1 skills=subject-boundaries@v1" in text


def test_a2a_marks_the_task_failed_instead_of_raising() -> None:
    task = _send(_service(UnconfiguredGateway("no key")), "Bom dia", {"strategy": "agent"})
    assert task["status"]["state"] == "TASK_STATE_FAILED"
    message = task["status"]["message"]["parts"][0]["text"]
    assert message == "error: agent:langgraph failed: model unavailable: no key"


def test_a2a_rejects_unknown_options_as_failed_task() -> None:
    task = _send(_service(UnconfiguredGateway("no key")), "oi", {"strategy": "magic"})
    assert task["status"]["state"] == "TASK_STATE_FAILED"
    assert "unknown strategy: magic" in task["status"]["message"]["parts"][0]["text"]
