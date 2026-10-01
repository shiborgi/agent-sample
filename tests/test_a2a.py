"""A2A ponta a ponta sobre ASGI, sem rede: sucesso, falha e progresso por etapa."""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from agent_sample.application.a2a.server import build_server
from tests.fakes import EXAMPLES, isolated_service

API_KEY_DIFF = (EXAMPLES / "diffs" / "api_key.diff").read_text()


def _payload(method: str, text: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {
            "message": {"messageId": "m-1", "role": "ROLE_USER", "parts": [{"text": text}]},
            "metadata": metadata,
        },
    }


def _post(service: Any, method: str, text: str, metadata: dict[str, Any]) -> httpx.Response:
    async def send() -> httpx.Response:
        app = build_server(service, "http://test", "1.0.0")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/", headers={"A2A-Version": "1.0"}, json=_payload(method, text, metadata)
            )

    return asyncio.run(send())


def _task(service: Any, text: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    response = _post(service, "SendMessage", text, metadata or {})
    assert response.status_code == 200
    return response.json()["result"]["task"]


def test_a2a_returns_structured_and_readable_review(tmp_path: Path) -> None:
    task = _task(isolated_service(tmp_path), API_KEY_DIFF)
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    data, text = task["artifacts"][0]["parts"]
    assert data["data"]["decision"] == "request_changes"
    assert data["data"]["findings"][0]["category"] == "security"
    assert text["text"].startswith("decision: request_changes")


def test_a2a_accepts_options_per_request(tmp_path: Path) -> None:
    metadata = {"mode": "workflow", "format": "json", "focus": ["security"]}
    task = _task(isolated_service(tmp_path), API_KEY_DIFF, metadata)
    text = task["artifacts"][0]["parts"][1]["text"]
    assert (
        json.loads(text)["trace"]["steps"][3]["detail"] == "mode workflow: deterministic steps only"
    )


def test_a2a_marks_failures_without_raising(tmp_path: Path) -> None:
    service = isolated_service(tmp_path)
    task = _task(service, "")
    assert task["status"]["state"] == "TASK_STATE_FAILED"
    assert (
        task["status"]["message"]["parts"][0]["text"] == "error: diff is empty: nothing to review"
    )
    task = _task(service, API_KEY_DIFF, {"mode": "magic"})
    assert task["status"]["state"] == "TASK_STATE_FAILED"
    assert "unknown mode: magic" in task["status"]["message"]["parts"][0]["text"]
    task = _task(service, API_KEY_DIFF, {"mode": "agent"})
    assert "MODEL_API_KEY is not set" in task["status"]["message"]["parts"][0]["text"]


def test_a2a_streams_one_status_update_per_step(tmp_path: Path) -> None:
    response = _post(isolated_service(tmp_path), "SendStreamingMessage", API_KEY_DIFF, {})
    assert response.status_code == 200
    events = [
        json.loads(line.removeprefix("data:"))["result"]
        for line in response.text.splitlines()
        if line.startswith("data:")
    ]
    messages = [
        event["statusUpdate"]["status"]["message"]["parts"][0]["text"]
        for event in events
        if "statusUpdate" in event and "message" in event["statusUpdate"]["status"]
    ]
    steps = [message.split(":")[0] for message in messages[1:10]]
    assert steps == [
        "obtain",
        "normalize",
        "checks",
        "plan",
        "agentic_review",
        "validate",
        "consolidate",
        "decide",
        "publish",
    ]
    assert events[-1]["statusUpdate"]["status"]["state"] == "TASK_STATE_COMPLETED"


def test_agent_card_announces_review_and_plugin_reviewers(tmp_path: Path) -> None:
    async def fetch() -> dict[str, Any]:
        app = build_server(isolated_service(tmp_path), "http://test", "1.0.0")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return (await client.get("/.well-known/agent-card.json")).json()

    card = asyncio.run(fetch())
    ids = [skill["id"] for skill in card["skills"]]
    assert ids[0] == "code_review"
    assert "code-review:security-reviewer" in ids
    assert "code-review@1.0.0" in card["skills"][0]["tags"]
