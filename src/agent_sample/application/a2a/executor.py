import json
import uuid
from dataclasses import asdict

from a2a.helpers import (
    get_message_text,
    new_data_part,
    new_task,
    new_text_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import TaskState

from agent_sample.application.a2a.options import request_options, request_ref
from agent_sample.application.service import ReviewService, error_message
from agent_sample.domain.model import StepRecord


class ReviewExecutor(AgentExecutor):
    def __init__(self, service: ReviewService) -> None:
        self._service = service

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.current_task:
            task = context.current_task
        else:
            # Não usa new_task_from_user_message: ele recusa texto vazio antes de podermos
            # marcar a tarefa como falha com uma mensagem clara.
            task = new_task(
                context.task_id or str(uuid.uuid4()),
                context.context_id or str(uuid.uuid4()),
                TaskState.TASK_STATE_SUBMITTED,
                history=[context.message] if context.message else None,
            )
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)
        await updater.update_status(
            state=TaskState.TASK_STATE_WORKING, message=new_text_message("review started")
        )

        async def progress(step: StepRecord) -> None:
            await updater.update_status(
                state=TaskState.TASK_STATE_WORKING,
                message=new_text_message(f"{step.name}: {step.outcome} — {step.detail}"),
            )

        text = get_message_text(context.message) if context.message else ""
        try:
            metadata = dict(context.metadata or {})
            options = request_options(metadata, self._service.defaults)
            result = await self._service.review(request_ref(text, metadata), options, progress)
        except Exception as exc:
            await updater.failed(new_text_message(error_message(exc)))
            return
        data = json.loads(json.dumps(asdict(result.review)))
        await updater.add_artifact(
            parts=[
                new_data_part(data, media_type="application/json"),
                new_text_part(text=result.output, media_type="text/plain"),
            ],
            name="review",
        )
        await updater.complete(new_text_message(result.review.summary))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            return
        updater = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)
        await updater.update_status(
            state=TaskState.TASK_STATE_CANCELED, message=new_text_message("canceled")
        )
