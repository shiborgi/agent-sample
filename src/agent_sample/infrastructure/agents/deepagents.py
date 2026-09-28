from typing import Any

from langchain_core.tools import StructuredTool

from agent_sample.domain.content import AgentRequest
from agent_sample.domain.errors import AgentFailed
from agent_sample.domain.ports import ToolCatalog, ToolSpec
from agent_sample.infrastructure.agents.answer import AnswerReader
from agent_sample.infrastructure.content.render import render_prompt
from agent_sample.infrastructure.model.langchain_chat import GatewayChatModel
from agent_sample.infrastructure.model.ports import ModelGateway


class DeepAgentsAgent[T]:
    """Agente do DeepAgents; recebe as mesmas ferramentas do domínio convertidas genericamente.

    O DeepAgents traz ferramentas próprias sobre um sistema de arquivos virtual em memória; a
    escrita nele é negada para que todas as ferramentas do agente sejam somente leitura.
    """

    name = "deepagents"

    def __init__(self, gateway: ModelGateway, read: AnswerReader[T]) -> None:
        self._gateway = gateway
        self._read = read

    async def run(self, request: AgentRequest, tools: ToolCatalog) -> T:
        from deepagents import FilesystemPermission, create_deep_agent

        agent = create_deep_agent(
            model=GatewayChatModel(self._gateway),
            tools=[_tool(spec, tools) for spec in tools.specs()],
            system_prompt=render_prompt(request.prompt, request.skills),
            permissions=[FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")],
        )
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": request.text}]},
            config={"recursion_limit": request.max_tool_rounds * 4},
        )
        messages = result["messages"]
        if not messages:
            raise AgentFailed(self.name, "agent ended without an answer")
        content = messages[-1].content
        return self._read(content if isinstance(content, str) else str(content), self.name)


def _tool(spec: ToolSpec, catalog: ToolCatalog) -> StructuredTool:
    async def call(**arguments: Any) -> str:
        return await catalog.call(spec.name, arguments)

    return StructuredTool.from_function(
        coroutine=call,
        name=spec.name,
        description=spec.description,
        args_schema=spec.parameters,
    )
