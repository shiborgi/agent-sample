import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from a2a.helpers import get_message_text, new_task, new_text_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import TaskState

from agent_sample.application.a2a.options import request_options
from agent_sample.application.a2a.text import artifact_text
from agent_sample.application.review import ReviewService
from agent_sample.application.review_output import review_json
from agent_sample.application.service import ClassificationService, error_message
from agent_sample.domain.errors import UnknownOption

CLASSIFY_KEYS = ("strategy", "engine", "agent", "prompt_version")
# `repo` nunca vem da requisição: um cliente remoto não escolhe caminhos do servidor.
REVIEW_KEYS = ("strategy", "engine", "agent", "prompt_version", "skills", "focus", "language")
REVIEW_LISTS = ("skills", "focus")


# Recebe o texto da mensagem e o metadata; devolve o texto do artefato e o media type dele.
Handler = Callable[[str, dict[str, Any]], Awaitable[tuple[str, str]]]


def classify_handler(service: ClassificationService) -> Handler:
    async def handle(text: str, metadata: dict[str, Any]) -> tuple[str, str]:
        options = request_options(metadata, service.defaults, CLASSIFY_KEYS)
        return artifact_text(await service.classify(text, options)), "text/plain"

    return handle


def review_handler(service: ReviewService) -> Handler:
    async def handle(text: str, metadata: dict[str, Any]) -> tuple[str, str]:
        options = request_options(metadata, service.defaults, REVIEW_KEYS, REVIEW_LISTS)
        return review_json(await service.review(text, options)), "application/json"

    return handle


class SkillExecutor(AgentExecutor):
    """Encaminha cada requisição à skill pedida em `metadata.skill` (padrão: a primeira)."""

    def __init__(self, handlers: dict[str, Handler]) -> None:
        self._handlers = handlers
        self._default = next(iter(handlers))

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.current_task:
            task = context.current_task
        else:
            # Não usa new_task_from_user_message: ele recusa texto vazio antes da validação da
            # aplicação, e a mensagem vazia precisa virar tarefa com falha, não exceção.
            task = new_task(
                task_id=context.task_id or str(uuid.uuid4()),
                context_id=context.context_id or str(uuid.uuid4()),
                state=TaskState.TASK_STATE_SUBMITTED,
                history=[context.message] if context.message else [],
            )
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)
        skill = context.metadata.get("skill", self._default)
        await updater.update_status(
            state=TaskState.TASK_STATE_WORKING,
            message=new_text_message(f"Executando {skill}..."),
        )
        query = get_message_text(context.message) if context.message else ""
        try:
            handler = self._handlers.get(skill)
            if handler is None:
                raise UnknownOption("skill", str(skill), tuple(self._handlers))
            text, media_type = await handler(query or "", context.metadata)
        except Exception as exc:
            await updater.failed(new_text_message(error_message(exc)))
            return
        await updater.add_artifact(parts=[new_text_part(text=text, media_type=media_type)])
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
