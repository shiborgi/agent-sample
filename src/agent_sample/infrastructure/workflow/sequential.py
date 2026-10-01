from collections.abc import Sequence

from agent_sample.domain.ports import ProgressListener
from agent_sample.domain.workflow import ReviewContext, ReviewState, WorkflowStep


class SequentialEngine:
    """Executa as etapas do domínio em ordem e avisa o progresso depois de cada uma."""

    name = "sequential"

    async def run(
        self,
        steps: Sequence[WorkflowStep],
        state: ReviewState,
        context: ReviewContext,
        on_step: ProgressListener | None = None,
    ) -> ReviewState:
        for step in steps:
            state = await step.run(state, context)
            if on_step is not None:
                await on_step(state.trace.steps[-1])
        return state
