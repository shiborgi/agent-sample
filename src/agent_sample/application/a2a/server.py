import uvicorn
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from starlette.applications import Starlette

from agent_sample.application.a2a.card import agent_card
from agent_sample.application.a2a.executor import ReviewExecutor
from agent_sample.application.service import ReviewService


def build_server(service: ReviewService, url: str, version: str) -> Starlette:
    card = agent_card(url, service.catalog.select(()), version)
    handler = DefaultRequestHandler(
        agent_executor=ReviewExecutor(service),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = [*create_agent_card_routes(card), *create_jsonrpc_routes(handler, "/")]
    return Starlette(routes=routes)


def serve(service: ReviewService, version: str, host: str = "127.0.0.1", port: int = 9999) -> None:
    url = f"http://{host}:{port}"
    uvicorn.run(build_server(service, url, version), host=host, port=port)
