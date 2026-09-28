"""Único ponto que conhece as implementações concretas e as liga às abstrações do domínio."""

import os
import sys
from collections.abc import Callable
from pathlib import Path

from agent_sample.application.service import ClassificationService, ClassifyOptions, error_message
from agent_sample.domain.content import CLASSIFY_TASK, SkillVersion
from agent_sample.domain.model import ContentError, SubjectError, UnknownOption
from agent_sample.domain.ports import (
    Agent,
    ModelGateway,
    Predictor,
    SubjectClassifier,
    WorkflowEngine,
)
from agent_sample.domain.strategies import (
    AgentStrategy,
    HybridStrategy,
    PredictionStrategy,
    WorkflowStrategy,
)
from agent_sample.infrastructure.agents.deepagents import DeepAgentsAgent
from agent_sample.infrastructure.agents.langgraph import LangGraphAgent
from agent_sample.infrastructure.content.files import FileContentLibrary
from agent_sample.infrastructure.model.openai_compatible import OpenAICompatibleGateway
from agent_sample.infrastructure.model.unconfigured import UnconfiguredGateway
from agent_sample.infrastructure.prediction.laya import LayaPredictor
from agent_sample.infrastructure.workflow.langgraph import LangGraphEngine
from agent_sample.infrastructure.workflow.sequential import SequentialEngine

CONTENT_ROOT = Path(__file__).parent / "content"

ENGINES: dict[str, Callable[[], WorkflowEngine]] = {
    "sequential": SequentialEngine,
    "langgraph": LangGraphEngine,
}
AGENTS: dict[str, Callable[[ModelGateway], Agent]] = {
    "langgraph": LangGraphAgent,
    "deepagents": DeepAgentsAgent,
}


class Composition:
    def __init__(
        self,
        content: FileContentLibrary,
        gateway: ModelGateway,
        predictor: Predictor,
    ) -> None:
        content.require(CLASSIFY_TASK)
        self.content = content
        self._gateway = gateway
        self._predictor = predictor

    def build(self, options: ClassifyOptions) -> SubjectClassifier:
        return _choose("strategy", options.strategy, STRATEGIES)(self, options)

    def implementations(self) -> tuple[SubjectClassifier, ...]:
        """Todas as formas concretas de executar, para comparação lado a lado."""
        base = ClassifyOptions()
        return (
            *(self.build(base.merge(strategy="workflow", engine=name)) for name in ENGINES),
            *(self.build(base.merge(strategy="agent", agent=name)) for name in AGENTS),
            self.build(base.merge(strategy="prediction")),
        )

    def workflow(self, options: ClassifyOptions) -> WorkflowStrategy:
        return WorkflowStrategy(_choose("engine", options.engine, ENGINES)())

    def agent(self, options: ClassifyOptions) -> AgentStrategy:
        agent = _choose("agent", options.agent, AGENTS)(self._gateway)
        prompt = self.content.prompt(CLASSIFY_TASK.prompt, options.prompt_version)
        return AgentStrategy(agent, prompt, self._skills(options.skills))

    def prediction(self, options: ClassifyOptions) -> PredictionStrategy:
        del options
        return PredictionStrategy(self._predictor)

    def _skills(self, pins: tuple[str, ...]) -> tuple[SkillVersion, ...]:
        versions: dict[str, str] = {}
        for pin in pins:
            name, sep, version = pin.partition("@")
            if not sep or name not in CLASSIFY_TASK.skills:
                raise ContentError(
                    f"invalid skill pin: {pin} (use name@version with one of "
                    f"{', '.join(CLASSIFY_TASK.skills)})"
                )
            versions[name] = version
        return tuple(self.content.skill(name, versions.get(name)) for name in CLASSIFY_TASK.skills)


STRATEGIES: dict[str, Callable[[Composition, ClassifyOptions], SubjectClassifier]] = {
    "workflow": Composition.workflow,
    "agent": Composition.agent,
    "hybrid": lambda root, options: HybridStrategy(root.workflow(options), root.agent(options)),
    "prediction": Composition.prediction,
}


def _choose[T](kind: str, name: str, registry: dict[str, T]) -> T:
    if name not in registry:
        raise UnknownOption(kind, name, tuple(registry))
    return registry[name]


def gateway_from_env() -> ModelGateway:
    api_key = os.environ.get("MODEL_API_KEY", "")
    if not api_key:
        return UnconfiguredGateway("MODEL_API_KEY is not set")
    return OpenAICompatibleGateway(
        base_url=os.environ.get("MODEL_BASE_URL", "https://api.openai.com/v1"),
        api_key=api_key,
        model=os.environ.get("MODEL_NAME", "gpt-4o-mini"),
    )


def defaults_from_env() -> ClassifyOptions:
    return ClassifyOptions().merge(
        strategy=os.environ.get("STRATEGY"),
        engine=os.environ.get("ENGINE"),
        agent=os.environ.get("AGENT"),
        prompt_version=os.environ.get("PROMPT_VERSION"),
    )


def bootstrap() -> tuple[ClassificationService, Composition]:
    """Carrega e valida conteúdo e padrões na inicialização, antes de qualquer classificação."""
    content = FileContentLibrary(Path(os.environ.get("CONTENT_DIR", CONTENT_ROOT)))
    composition = Composition(content, gateway_from_env(), LayaPredictor())
    service = ClassificationService(composition.build, defaults_from_env())
    service.build(service.defaults)
    return service, composition


def cli_main() -> None:
    from agent_sample.application.cli.app import run

    service, composition = _bootstrap_or_exit()
    run(service, composition.implementations, composition.content)


def a2a_main() -> None:
    from agent_sample.application.a2a.server import serve

    service, _ = _bootstrap_or_exit()
    serve(service)


def _bootstrap_or_exit() -> tuple[ClassificationService, Composition]:
    try:
        return bootstrap()
    except SubjectError as exc:
        print(error_message(exc), file=sys.stderr)
        raise SystemExit(1) from None
