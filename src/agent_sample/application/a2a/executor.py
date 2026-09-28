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

from agent_sample.application.a2a.text import artifact_text
from agent_sample.domain.ports import SubjectClassifier
from agent_sample.domain.session import classify_subject


class SubjectExecutor(AgentExecutor):
    def __init__(self, classifier: SubjectClassifier) -> None:
        self._classifier = classifier

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
        verdict = await classify_subject(query or "", self._classifier)
        await updater.add_artifact(
            parts=[new_text_part(text=artifact_text(verdict), media_type="text/plain")]
        )
        await updater.update_status(
            state=TaskState.TASK_STATE_COMPLETED,
            message=new_text_message(artifact_text(verdict)),
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            return
        updater = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)
        await updater.update_status(
            state=TaskState.TASK_STATE_CANCELED,
            message=new_text_message("canceled"),
        )
