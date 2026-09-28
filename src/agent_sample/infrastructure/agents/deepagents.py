from typing import Any

from langchain_core.tools import StructuredTool

from agent_sample.domain.model import ClassificationFailed
from agent_sample.domain.policy import MAX_TOOL_ROUNDS
from agent_sample.domain.ports import ModelGateway, ToolCatalog, ToolSpec
from agent_sample.infrastructure.model.langchain_chat import GatewayChatModel


class DeepAgentsAgent:
    """Agente do DeepAgents; recebe as mesmas ferramentas do domínio convertidas genericamente."""

    name = "deepagents"

    def __init__(self, gateway: ModelGateway) -> None:
        self._gateway = gateway

    async def run(self, system: str, user: str, tools: ToolCatalog) -> str:
        from deepagents import create_deep_agent

        agent = create_deep_agent(
            model=GatewayChatModel(self._gateway),
            tools=[_tool(spec, tools) for spec in tools.specs()],
            system_prompt=system,
        )
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": user}]},
            config={"recursion_limit": MAX_TOOL_ROUNDS * 4},
        )
        messages = result["messages"]
        if not messages:
            raise ClassificationFailed(self.name, "agent ended without an answer")
        content = messages[-1].content
        return content if isinstance(content, str) else str(content)


def _tool(spec: ToolSpec, catalog: ToolCatalog) -> StructuredTool:
    async def call(**arguments: Any) -> str:
        return await catalog.call(spec.name, arguments)

    return StructuredTool.from_function(
        coroutine=call,
        name=spec.name,
        description=spec.description,
        args_schema=spec.parameters,
    )
