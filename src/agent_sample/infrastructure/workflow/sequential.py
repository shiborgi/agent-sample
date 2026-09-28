from collections.abc import Sequence

from agent_sample.domain.workflow import WorkflowState, WorkflowStep


class SequentialEngine:
    name = "sequential"

    async def run(self, steps: Sequence[WorkflowStep], state: WorkflowState) -> WorkflowState:
        for step in steps:
            state = step.run(state)
        return state
