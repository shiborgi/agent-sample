from collections.abc import Callable, Sequence
from typing import Any

from langgraph.graph import END, START, StateGraph

from agent_sample.domain.workflow import WorkflowState, WorkflowStep


class LangGraphEngine:
    """Cada etapa do workflow vira um nó de um grafo linear do LangGraph."""

    name = "langgraph"

    async def run(self, steps: Sequence[WorkflowStep], state: WorkflowState) -> WorkflowState:
        builder = StateGraph(dict)
        previous = START
        for step in steps:
            builder.add_node(step.name, _node(step))
            builder.add_edge(previous, step.name)
            previous = step.name
        builder.add_edge(previous, END)
        result = await builder.compile().ainvoke({"state": state})
        return result["state"]


def _node(step: WorkflowStep) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def node(graph_state: dict[str, Any]) -> dict[str, Any]:
        return {"state": step.run(graph_state["state"])}

    return node
