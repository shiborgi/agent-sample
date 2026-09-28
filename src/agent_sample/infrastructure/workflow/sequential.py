from collections.abc import Sequence

from agent_sample.domain.workflow import WorkflowStep


class SequentialEngine:
    name = "sequential"

    async def run[S](self, steps: Sequence[WorkflowStep[S]], state: S) -> S:
        for step in steps:
            state = step.run(state)
        return state
