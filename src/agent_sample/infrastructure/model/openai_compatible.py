import json
from collections.abc import Sequence

import httpx

from agent_sample.domain.ports import ToolSpec
from agent_sample.infrastructure.model.ports import ChatMessage, Completion, ToolCall


class OpenAICompatibleGateway:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] = (),
    ) -> Completion:
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [_message(message) for message in messages],
        }
        if tools:
            payload["tools"] = [_tool(spec) for spec in tools]
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
        if response.status_code >= 400:
            raise RuntimeError(f"model gateway failed with HTTP {response.status_code}")
        message = response.json()["choices"][0]["message"]
        return Completion(
            text=message.get("content") or "",
            tool_calls=tuple(_tool_call(call) for call in message.get("tool_calls") or []),
        )


def _message(message: ChatMessage) -> dict[str, object]:
    if message.role == "tool":
        return {
            "role": "tool",
            "content": message.content,
            "tool_call_id": message.tool_call_id,
        }
    payload: dict[str, object] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
            }
            for call in message.tool_calls
        ]
    return payload


def _tool(spec: ToolSpec) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        },
    }


def _tool_call(call: dict[str, object]) -> ToolCall:
    function = call["function"]
    if not isinstance(function, dict):
        raise RuntimeError("model gateway returned an invalid tool call")
    raw_arguments = function.get("arguments") or "{}"
    arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
    if not isinstance(arguments, dict):
        raise RuntimeError("model gateway returned invalid tool arguments")
    call_id = call.get("id")
    name = function.get("name")
    if not isinstance(call_id, str) or not isinstance(name, str):
        raise RuntimeError("model gateway returned an invalid tool call")
    return ToolCall(id=call_id, name=name, arguments=arguments)
