import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from agent_sample.application.a2a.server import build_server
from agent_sample.application.review import ReviewOptions, ReviewService
from agent_sample.application.service import ClassificationService, ClassifyOptions
from agent_sample.infrastructure.model.unconfigured import UnconfiguredGateway
from tests.fakes import ScriptedGateway, ScriptedReviewGateway, composition, review_service

Services = tuple[ClassificationService, ReviewService]
EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "review"


def _service(gateway: Any, review_defaults: ReviewOptions | None = None) -> Services:
    root = composition(gateway)
    return ClassificationService(root.build, ClassifyOptions()), review_service(
        root, review_defaults
    )


def _send(services: Services, text: str, metadata: dict[str, Any]) -> dict[str, Any]:
    async def send() -> dict[str, Any]:
        app = build_server(*services, "http://test")
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


def _review(task: dict[str, Any]) -> dict[str, Any]:
    part = task["artifacts"][0]["parts"][0]
    assert part["mediaType"] == "application/json"
    return json.loads(part["text"])


def test_a2a_reviews_a_diff_with_the_server_default() -> None:
    diff = (EXAMPLES / "api_key.diff").read_text()
    task = _send(_service(UnconfiguredGateway("no key")), diff, {"skill": "review_change"})
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    review = _review(task)
    assert review["decision"] == "request_changes"
    assert review["findings"][0]["severity"] == "critical"
    assert any(step["outcome"] == "failed" for step in review["trace"])


def test_a2a_review_options_go_per_request() -> None:
    diff = (EXAMPLES / "debug_print.diff").read_text()
    metadata = {
        "skill": "review_change",
        "strategy": "agent",
        "agent": "deepagents",
        "focus": ["tests", "security"],
    }
    review = _review(_send(_service(ScriptedReviewGateway()), diff, metadata))
    assert review["reviewed_by"] == "agent:deepagents"
    (agent,) = [step for step in review["trace"] if step["kind"] == "agent"]
    assert agent["skills"] == ["python-practices@v1"]


def test_a2a_client_cannot_choose_the_server_repository(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "pricing.py").write_text("segredo do servidor\n")
    gateway = ScriptedReviewGateway()
    services = _service(gateway, ReviewOptions(strategy="agent"))
    diff = (EXAMPLES / "debug_print.diff").read_text()
    _send(services, diff, {"skill": "review_change", "repo": str(tmp_path)})
    results = [message.content for message in gateway.calls[-1][0] if message.role == "tool"]
    assert "erro: repositório indisponível nesta revisão; use só o diff" in results


def test_a2a_review_failure_marks_the_task_failed() -> None:
    task = _send(_service(UnconfiguredGateway("no key")), "", {"skill": "review_change"})
    assert task["status"]["state"] == "TASK_STATE_FAILED"
    assert task["status"]["message"]["parts"][0]["text"] == "error: diff is empty"
    bad = _send(
        _service(UnconfiguredGateway("no key")),
        "x",
        {"skill": "review_change", "focus": 3},
    )
    assert bad["status"]["state"] == "TASK_STATE_FAILED"
    assert "unknown focus value: 3" in bad["status"]["message"]["parts"][0]["text"]


def test_a2a_unknown_skill_is_a_failed_task() -> None:
    task = _send(_service(UnconfiguredGateway("no key")), "oi", {"skill": "translate"})
    assert task["status"]["state"] == "TASK_STATE_FAILED"
    assert (
        "unknown skill: translate (choose from classify_subject, review_change)"
        in (task["status"]["message"]["parts"][0]["text"])
    )


def test_a2a_empty_message_is_a_failed_task_for_the_classifier_too() -> None:
    task = _send(_service(UnconfiguredGateway("no key")), "", {})
    assert task["status"]["state"] == "TASK_STATE_FAILED"
    assert task["status"]["message"]["parts"][0]["text"] == "error: message is empty"
