from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from agent_sample.domain.model import ClassificationFailed
from agent_sample.domain.policy import MAX_TOOL_ROUNDS
from agent_sample.domain.ports import ChatMessage, ModelGateway, ToolCall, ToolCatalog
from agent_sample.infrastructure.runtime.parsing import parse_verdict
from agent_sample.infrastructure.runtime.prompt import classify_prompt


class LangGraphSubjectClassifier:
    runtime = "langgraph"

    def __init__(self, gateway: ModelGateway, catalog: ToolCatalog) -> None:
        self._gateway = gateway
        self._catalog = catalog

    async def classify(self, text: str) -> Any:
        graph = _graph(self._gateway, self._catalog)
        result = await graph.ainvoke(
            {
                "messages": [
                    _dump(ChatMessage(role="system", content=classify_prompt())),
                    _dump(ChatMessage(role="user", content=text)),
                ],
                "rounds": 0,
            }
        )
        last = _load(result["messages"][-1])
        if last.role != "assistant" or last.tool_calls:
            raise ClassificationFailed(self.runtime, "classifier ended without an answer")
        return parse_verdict(last.content, self.runtime)


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
