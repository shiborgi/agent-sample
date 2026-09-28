from typing import Any

from agent_sample.domain.model import ClassificationFailed
from agent_sample.domain.policy import MAX_TOOL_ROUNDS
from agent_sample.domain.ports import ModelGateway, ToolCatalog
from agent_sample.infrastructure.model.langchain_chat import GatewayChatModel
from agent_sample.infrastructure.runtime.parsing import parse_verdict
from agent_sample.infrastructure.runtime.prompt import classify_prompt


class DeepAgentsSubjectClassifier:
    runtime = "deepagents"

    def __init__(self, gateway: ModelGateway, catalog: ToolCatalog) -> None:
        self._gateway = gateway
        self._catalog = catalog
        self._agent: Any = None

    async def classify(self, text: str) -> Any:
        result = await self._build().ainvoke(
            {"messages": [{"role": "user", "content": text}]},
            config={"recursion_limit": MAX_TOOL_ROUNDS * 4},
        )
        messages = result["messages"]
        if not messages:
            raise ClassificationFailed(self.runtime, "classifier ended without an answer")
        last = messages[-1]
        content = last.content if hasattr(last, "content") else last["content"]
        if not isinstance(content, str):
            content = str(content)
        return parse_verdict(content, self.runtime)

    def _build(self) -> Any:
        if self._agent is None:
            from deepagents import create_deep_agent

            self._agent = create_deep_agent(
                model=GatewayChatModel(self._gateway),
                tools=[_list_subjects(self._catalog)],
                system_prompt=classify_prompt(),
            )
        return self._agent


def _list_subjects(catalog: ToolCatalog) -> Any:
    async def list_subjects() -> str:
        """Lista os assuntos permitidos para classificar a mensagem."""
        return await catalog.call("list_subjects", {})

    return list_subjects
