import os

from agent_sample.domain.ports import SubjectClassifier
from agent_sample.infrastructure.model.openai_compatible import OpenAICompatibleGateway
from agent_sample.infrastructure.runtime.deepagents import DeepAgentsSubjectClassifier
from agent_sample.infrastructure.runtime.langgraph import LangGraphSubjectClassifier
from agent_sample.infrastructure.runtime.laya import LayaSubjectClassifier
from agent_sample.infrastructure.tools.subjects import SubjectCatalog

RUNTIMES = ("langgraph", "deepagents", "laya")


def build_classifier(runtime: str) -> SubjectClassifier:
    if runtime == "laya":
        return LayaSubjectClassifier()
    if runtime not in {"langgraph", "deepagents"}:
        raise ValueError(f"unknown runtime: {runtime}")
    gateway = OpenAICompatibleGateway(
        base_url=os.environ.get("MODEL_BASE_URL", "https://api.openai.com/v1"),
        api_key=_api_key(),
        model=os.environ.get("MODEL_NAME", "gpt-4o-mini"),
    )
    catalog = SubjectCatalog()
    if runtime == "langgraph":
        return LangGraphSubjectClassifier(gateway, catalog)
    return DeepAgentsSubjectClassifier(gateway, catalog)


def build_all() -> tuple[SubjectClassifier, ...]:
    return tuple(build_classifier(runtime) for runtime in RUNTIMES)


def cli_main() -> None:
    from agent_sample.application.cli.app import run

    run(build_classifier, build_all)


def a2a_main() -> None:
    from agent_sample.application.a2a.server import serve

    serve(build_classifier(os.environ.get("CLASSIFIER", "langgraph")))


def _api_key() -> str:
    api_key = os.environ.get("MODEL_API_KEY", "")
    if not api_key:
        raise RuntimeError("MODEL_API_KEY is required")
    return api_key
