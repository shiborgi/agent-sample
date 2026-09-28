from a2a.helpers import (
    get_message_text,
    new_task_from_user_message,
    new_text_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import TaskState

from agent_sample.application.a2a.options import request_options
from agent_sample.application.a2a.text import artifact_text
from agent_sample.application.service import ClassificationService, error_message


class SubjectExecutor(AgentExecutor):
    def __init__(self, service: ClassificationService) -> None:
        self._service = service

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.current_task:
            task = context.current_task
        else:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)
        await updater.update_status(
            state=TaskState.TASK_STATE_WORKING,
            message=new_text_message("Classificando assunto..."),
        )
        query = get_message_text(context.message) if context.message else ""
        try:
            options = request_options(context.metadata, self._service.defaults)
            verdict = await self._service.classify(query or "", options)
        except Exception as exc:
            await updater.failed(new_text_message(error_message(exc)))
            return
        text = artifact_text(verdict)
        await updater.add_artifact(parts=[new_text_part(text=text, media_type="text/plain")])
        await updater.complete(new_text_message(text))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            return
        updater = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)
        await updater.update_status(
            state=TaskState.TASK_STATE_CANCELED,
            message=new_text_message("canceled"),
        )
