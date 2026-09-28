"""Único ponto que conhece as implementações concretas e as liga às abstrações do domínio."""

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_sample.application.review import ReviewOptions, ReviewService
from agent_sample.application.service import ClassificationService, ClassifyOptions, error_message
from agent_sample.domain.content import CLASSIFY_TASK, REVIEW_TASK, AgentTask, SkillVersion
from agent_sample.domain.errors import ContentError, DomainError, UnknownOption
from agent_sample.domain.ports import Agent, Predictor, SubjectClassifier, WorkflowEngine
from agent_sample.domain.review.ports import ChangeReviewer, DiffSource, Repository
from agent_sample.domain.review.strategies import AgentReviewer, HybridReviewer, WorkflowReviewer
from agent_sample.domain.strategies import (
    AgentStrategy,
    HybridStrategy,
    PredictionStrategy,
    WorkflowStrategy,
)
from agent_sample.infrastructure.agents.answer import AnswerReader, parse_answer, parse_review
from agent_sample.infrastructure.agents.deepagents import DeepAgentsAgent
from agent_sample.infrastructure.agents.langgraph import LangGraphAgent
from agent_sample.infrastructure.content.files import FileContentLibrary
from agent_sample.infrastructure.model.openai_compatible import OpenAICompatibleGateway
from agent_sample.infrastructure.model.ports import ModelGateway
from agent_sample.infrastructure.model.unconfigured import UnconfiguredGateway
from agent_sample.infrastructure.prediction.laya import LayaPredictor
from agent_sample.infrastructure.repository.git import GitDiffSource
from agent_sample.infrastructure.repository.local import LocalRepository
from agent_sample.infrastructure.workflow.langgraph import LangGraphEngine
from agent_sample.infrastructure.workflow.sequential import SequentialEngine

CONTENT_ROOT = Path(__file__).parent / "content"

ENGINES: dict[str, Callable[[], WorkflowEngine]] = {
    "sequential": SequentialEngine,
    "langgraph": LangGraphEngine,
}
# Cada framework de agente serve a qualquer tarefa: recebe o leitor da resposta da tarefa.
AGENTS: dict[str, Callable[[ModelGateway, AnswerReader[Any]], Agent[Any]]] = {
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
        content.check_tasks((CLASSIFY_TASK, REVIEW_TASK))
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
        agent = _choose("agent", options.agent, AGENTS)(self._gateway, parse_answer)
        prompt = self.content.prompt(CLASSIFY_TASK.prompt, options.prompt_version)
        return AgentStrategy(agent, prompt, self._skills(CLASSIFY_TASK, options.skills))

    def prediction(self, options: ClassifyOptions) -> PredictionStrategy:
        del options
        return PredictionStrategy(self._predictor)

    def reviewer(self, options: ReviewOptions) -> ChangeReviewer:
        return _choose("strategy", options.strategy, REVIEWERS)(self, options)

    def review_workflow(self, options: ReviewOptions) -> WorkflowReviewer:
        return WorkflowReviewer(_choose("engine", options.engine, ENGINES)())

    def review_agent(self, options: ReviewOptions) -> AgentReviewer:
        agent = _choose("agent", options.agent, AGENTS)(self._gateway, parse_review)
        prompt = self.content.prompt(REVIEW_TASK.prompt, options.prompt_version)
        skills = self._skills(REVIEW_TASK, options.skills)
        return AgentReviewer(agent, prompt, skills, _repository(options.repo))

    def diff_source(self, repo: str | None) -> DiffSource:
        return GitDiffSource(Path(repo or "."))

    def _skills(self, task: AgentTask, pins: tuple[str, ...]) -> tuple[SkillVersion, ...]:
        """Skills oferecidas à tarefa na versão padrão, ou na versão fixada por `nome@versão`."""
        offered = self.content.offered_skills(task)
        versions: dict[str, str] = {}
        for pin in pins:
            name, sep, version = pin.partition("@")
            if not sep or not self.content.accepts(task, name, version):
                raise ContentError(
                    f"invalid skill pin: {pin} (use name@version with one of {', '.join(offered)})"
                )
            versions[name] = version
        names = (*offered, *(name for name in versions if name not in offered))
        return tuple(self.content.skill(name, versions.get(name)) for name in names)


STRATEGIES: dict[str, Callable[[Composition, ClassifyOptions], SubjectClassifier]] = {
    "workflow": Composition.workflow,
    "agent": Composition.agent,
    "hybrid": lambda root, options: HybridStrategy(root.workflow(options), root.agent(options)),
    "prediction": Composition.prediction,
}


REVIEWERS: dict[str, Callable[[Composition, ReviewOptions], ChangeReviewer]] = {
    "workflow": Composition.review_workflow,
    "agent": Composition.review_agent,
    "hybrid": lambda root, options: HybridReviewer(
        root.review_workflow(options), root.review_agent(options)
    ),
}


def _repository(repo: str | None) -> Repository | None:
    return None if repo is None else LocalRepository(Path(repo))


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


def review_defaults_from_env() -> ReviewOptions:
    return ReviewOptions().merge(
        strategy=os.environ.get("REVIEW_STRATEGY"),
        engine=os.environ.get("REVIEW_ENGINE"),
        agent=os.environ.get("REVIEW_AGENT"),
        prompt_version=os.environ.get("REVIEW_PROMPT_VERSION"),
        repo=os.environ.get("REVIEW_REPO"),
    )


Services = tuple[ClassificationService, ReviewService, Composition]


def bootstrap() -> Services:
    """Carrega e valida conteúdo e padrões na inicialização, antes de qualquer uso."""
    content = FileContentLibrary(Path(os.environ.get("CONTENT_DIR", CONTENT_ROOT)))
    composition = Composition(content, gateway_from_env(), LayaPredictor())
    service = ClassificationService(composition.build, defaults_from_env())
    service.build(service.defaults)
    review = ReviewService(
        composition.reviewer, composition.diff_source, review_defaults_from_env()
    )
    review.build(review.defaults)
    return service, review, composition


def cli_main() -> None:
    from agent_sample.application.cli.app import run

    service, review, composition = _bootstrap_or_exit()
    run(service, composition.implementations, composition.content, review)


def a2a_main() -> None:
    from agent_sample.application.a2a.server import serve

    service, review, _ = _bootstrap_or_exit()
    serve(service, review)


def _bootstrap_or_exit() -> Services:
    try:
        return bootstrap()
    except DomainError as exc:
        print(error_message(exc), file=sys.stderr)
        raise SystemExit(1) from None
