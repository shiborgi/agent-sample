from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from agent_sample.domain.content import AgentAnswer, AgentRequest
from agent_sample.domain.model import ClassificationFailed
from agent_sample.domain.policy import MAX_TOOL_ROUNDS
from agent_sample.domain.ports import ToolCatalog
from agent_sample.infrastructure.agents.answer import parse_answer
from agent_sample.infrastructure.content.render import render_prompt
from agent_sample.infrastructure.model.ports import ChatMessage, ModelGateway, ToolCall


class LangGraphAgent:
    """Laço ReAct explícito: o modelo decide quando chamar ferramentas e quando responder."""

    name = "langgraph"

    def __init__(self, gateway: ModelGateway) -> None:
        self._gateway = gateway

    async def run(self, request: AgentRequest, tools: ToolCatalog) -> AgentAnswer:
        graph = _graph(self._gateway, tools)
        system = render_prompt(request.prompt, request.skills)
        result = await graph.ainvoke(
            {
                "messages": [
                    _dump(ChatMessage(role="system", content=system)),
                    _dump(ChatMessage(role="user", content=request.text)),
                ],
                "rounds": 0,
            }
        )
        last = _load(result["messages"][-1])
        if last.role != "assistant" or last.tool_calls:
            raise ClassificationFailed(self.name, "agent ended without an answer")
        return parse_answer(last.content, self.name)


def _graph(gateway: ModelGateway, catalog: ToolCatalog) -> Any:
    async def model(state: dict[str, Any]) -> dict[str, Any]:
        if state["rounds"] >= MAX_TOOL_ROUNDS:
            raise ClassificationFailed("langgraph", "tool round limit")
        completion = await gateway.complete(
            [_load(message) for message in state["messages"]],
            catalog.specs(),
        )
        message = ChatMessage(
            role="assistant",
            content=completion.text,
            tool_calls=completion.tool_calls,
        )
        rounds = state["rounds"] + (1 if completion.tool_calls else 0)
        return {"messages": [*state["messages"], _dump(message)], "rounds": rounds}

    async def tools(state: dict[str, Any]) -> dict[str, Any]:
        last = _load(state["messages"][-1])
        results: list[dict[str, Any]] = []
        for call in last.tool_calls:
            try:
                output = await catalog.call(call.name, call.arguments)
            except KeyError as exc:
                raise ClassificationFailed("langgraph", f"unknown tool: {call.name}") from exc
            results.append(_dump(ChatMessage(role="tool", content=output, tool_call_id=call.id)))
        return {"messages": [*state["messages"], *results], "rounds": state["rounds"]}

    def route(state: dict[str, Any]) -> Literal["tools", "end"]:
        last = _load(state["messages"][-1])
        if last.tool_calls and state["rounds"] <= MAX_TOOL_ROUNDS:
            return "tools"
        return "end"

    builder = StateGraph(dict)
    builder.add_node("model", model)
    builder.add_node("tools", tools)
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", route, {"tools": "tools", "end": END})
    builder.add_edge("tools", "model")
    return builder.compile()


def _dump(message: ChatMessage) -> dict[str, Any]:
    return {
        "role": message.role,
        "content": message.content,
        "tool_call_id": message.tool_call_id,
        "tool_calls": [_call(call) for call in message.tool_calls],
    }


def _call(call: ToolCall) -> dict[str, Any]:
    return {"id": call.id, "name": call.name, "arguments": call.arguments}


def _load(raw: dict[str, Any]) -> ChatMessage:
    return ChatMessage(
        role=raw["role"],
        content=raw["content"],
        tool_call_id=raw.get("tool_call_id"),
        tool_calls=tuple(
            ToolCall(id=call["id"], name=call["name"], arguments=call["arguments"])
            for call in raw.get("tool_calls") or []
        ),
    )
