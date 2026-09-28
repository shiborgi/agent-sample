import asyncio
import json

import httpx

from agent_sample.domain.ports import ChatMessage, ToolSpec
from agent_sample.infrastructure.model.openai_compatible import OpenAICompatibleGateway


def test_gateway_posts_openai_chat_completions() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "list_subjects",
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    gateway = OpenAICompatibleGateway("http://models.local/v1", "secret", "demo")
    completion = asyncio.run(_complete(gateway, handler))
    assert seen["url"] == "http://models.local/v1/chat/completions"
    assert seen["auth"] == "Bearer secret"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == "demo"
    assert body["tools"][0]["function"]["name"] == "list_subjects"
    assert completion.tool_calls[0].name == "list_subjects"


async def _complete(gateway: OpenAICompatibleGateway, handler: object) -> object:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    original = httpx.AsyncClient

    class Client(original):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = Client  # type: ignore[misc]
    try:
        return await gateway.complete(
            (ChatMessage(role="user", content="fui cobrado"),),
            (
                ToolSpec(
                    name="list_subjects",
                    description="lista",
                    parameters={"type": "object", "properties": {}},
                ),
            ),
        )
    finally:
        httpx.AsyncClient = original
