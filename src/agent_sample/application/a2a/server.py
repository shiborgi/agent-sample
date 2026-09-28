import uvicorn
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from starlette.applications import Starlette

from agent_sample.application.a2a.card import agent_card
from agent_sample.application.a2a.executor import SubjectExecutor
from agent_sample.domain.ports import SubjectClassifier


def build_server(classifier: SubjectClassifier, url: str) -> Starlette:
    card = agent_card(url)
    handler = DefaultRequestHandler(
        agent_executor=SubjectExecutor(classifier),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = [*create_agent_card_routes(card), *create_jsonrpc_routes(handler, "/")]
    return Starlette(routes=routes)


def serve(classifier: SubjectClassifier, host: str = "127.0.0.1", port: int = 9999) -> None:
    url = f"http://{host}:{port}"
    uvicorn.run(build_server(classifier, url), host=host, port=port)
