from collections.abc import Sequence

from agent_sample.domain.model import ModelUnavailable
from agent_sample.domain.ports import ChatMessage, Completion, ToolSpec


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
        raise ModelUnavailable(self._reason)
