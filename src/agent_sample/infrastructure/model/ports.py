"""Protocolo de chat com o modelo. Detalhe de infraestrutura: o domínio nunca o vê."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from agent_sample.domain.ports import ToolSpec


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()


class ModelGateway(Protocol):
    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] = (),
    ) -> Completion: ...
