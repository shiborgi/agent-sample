import uvicorn
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from starlette.applications import Starlette

from agent_sample.application.a2a.card import agent_card
from agent_sample.application.a2a.executor import SkillExecutor, classify_handler, review_handler
from agent_sample.application.review import ReviewService
from agent_sample.application.service import ClassificationService


def build_server(classify: ClassificationService, review: ReviewService, url: str) -> Starlette:
    card = agent_card(url)
    executor = SkillExecutor(
        {"classify_subject": classify_handler(classify), "review_change": review_handler(review)}
    )
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = [*create_agent_card_routes(card), *create_jsonrpc_routes(handler, "/")]
    return Starlette(routes=routes)


def serve(
    classify: ClassificationService,
    review: ReviewService,
    host: str = "127.0.0.1",
    port: int = 9999,
) -> None:
    url = f"http://{host}:{port}"
    uvicorn.run(build_server(classify, review, url), host=host, port=port)
