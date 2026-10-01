from collections.abc import Sequence

from agent_sample.domain.model import AgentUnavailable
from agent_sample.domain.ports import ToolSpec
from agent_sample.infrastructure.model.ports import ChatMessage, Completion


class UnconfiguredGateway:
    """Usado quando não há credencial: só falha se um agente realmente precisar do modelo."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] = (),
    ) -> Completion:
        del messages, tools
        raise AgentUnavailable(self._reason)
