from collections.abc import Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict, PrivateAttr

from agent_sample.domain.ports import ChatMessage, ModelGateway, ToolCall, ToolSpec


class GatewayChatModel(BaseChatModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _gateway: ModelGateway = PrivateAttr()
    _tools: tuple[ToolSpec, ...] = PrivateAttr(default=())

    def __init__(self, gateway: ModelGateway, tools: tuple[ToolSpec, ...] = ()) -> None:
        super().__init__()
        self._gateway = gateway
        self._tools = tools

    @property
    def _llm_type(self) -> str:
        return "gateway-chat"

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> "GatewayChatModel":
        del tool_choice, kwargs
        return GatewayChatModel(self._gateway, tuple(tool_spec(tool) for tool in tools))

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise RuntimeError("GatewayChatModel only supports async invocation")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        completion = await self._gateway.complete(
            tuple(to_domain(message) for message in messages),
            self._tools,
        )
        return ChatResult(generations=[ChatGeneration(message=to_ai(completion))])


def tool_spec(tool: Any) -> ToolSpec:
    if isinstance(tool, dict):
        function = tool.get("function", tool)
        return ToolSpec(
            name=str(function["name"]),
            description=str(function.get("description") or ""),
            parameters=dict(function.get("parameters") or {"type": "object", "properties": {}}),
        )
    schema: dict[str, Any] = {"type": "object", "properties": {}}
    args_schema = getattr(tool, "args_schema", None)
    if args_schema is not None and hasattr(args_schema, "model_json_schema"):
        schema = args_schema.model_json_schema()
    return ToolSpec(
        name=str(tool.name),
        description=str(getattr(tool, "description", "") or ""),
        parameters=schema,
    )


def to_domain(message: BaseMessage) -> ChatMessage:
    role = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}.get(
        message.type, "user"
    )
    calls = getattr(message, "tool_calls", None) or []
    return ChatMessage(
        role=role,  # type: ignore[arg-type]
        content=_content_text(message.content),
        tool_call_id=getattr(message, "tool_call_id", None),
        tool_calls=tuple(_tool_call(call) for call in calls),
    )


def _tool_call(call: dict[str, Any]) -> ToolCall:
    return ToolCall(
        id=str(call["id"]),
        name=str(call["name"]),
        arguments=dict(call.get("args") or {}),
    )


def to_ai(completion: Any) -> AIMessage:
    return AIMessage(
        content=completion.text,
        tool_calls=[
            {"name": call.name, "args": call.arguments, "id": call.id, "type": "tool_call"}
            for call in completion.tool_calls
        ],
    )


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return str(content)
