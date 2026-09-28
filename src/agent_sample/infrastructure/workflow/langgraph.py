from collections.abc import Callable, Sequence
from typing import Any

from langgraph.graph import END, START, StateGraph

from agent_sample.domain.workflow import WorkflowState, WorkflowStep


class LangGraphEngine:
    """Cada etapa do workflow vira um nó de um grafo linear do LangGraph, compilado uma vez."""

    name = "langgraph"

    def __init__(self) -> None:
        self._graphs: dict[tuple[WorkflowStep, ...], Any] = {}

    async def run(self, steps: Sequence[WorkflowStep], state: WorkflowState) -> WorkflowState:
        key = tuple(steps)
        graph = self._graphs.get(key)
        if graph is None:
            graph = self._graphs[key] = _compile(key)
        result = await graph.ainvoke({"state": state})
        return result["state"]


def _compile(steps: tuple[WorkflowStep, ...]) -> Any:
    builder = StateGraph(dict)
    previous = START
    for step in steps:
        builder.add_node(step.name, _node(step))
        builder.add_edge(previous, step.name)
        previous = step.name
    builder.add_edge(previous, END)
    return builder.compile()


def _node(step: WorkflowStep) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def node(graph_state: dict[str, Any]) -> dict[str, Any]:
        return {"state": step.run(graph_state["state"])}

    return node
