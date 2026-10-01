"""Único ponto que conhece as implementações concretas e as liga às portas do domínio."""

import importlib.metadata
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

import httpx

from agent_sample.application.service import ReviewOptions, ReviewService, error_message
from agent_sample.domain.model import ReviewError, UnknownOption
from agent_sample.domain.ports import AgentReviewer, PullRequestHost, Renderer
from agent_sample.domain.workflow import ReviewContext
from agent_sample.infrastructure.agents.deepagents import DeepAgentsReviewer
from agent_sample.infrastructure.model.openai_compatible import OpenAICompatibleGateway
from agent_sample.infrastructure.model.ports import ModelGateway
from agent_sample.infrastructure.model.unconfigured import UnconfiguredGateway
from agent_sample.infrastructure.output.pr_comments import PullRequestCommentsRenderer
from agent_sample.infrastructure.output.structured import JsonRenderer
from agent_sample.infrastructure.output.text import TextRenderer
from agent_sample.infrastructure.plugins.catalog import PluginCatalog, load_catalog, lock_sources
from agent_sample.infrastructure.plugins.sources import ReviewerConfig, builtin_source, load_config
from agent_sample.infrastructure.repository.git import GitRevisionSource
from agent_sample.infrastructure.repository.worktree import RepositoryReaders
from agent_sample.infrastructure.rest.client import RestClient
from agent_sample.infrastructure.rest.github import GitHubPullRequests, PullRequestPublisher
from agent_sample.infrastructure.workflow.sequential import SequentialEngine

BUILTIN_PLUGINS = Path(__file__).parent / "plugins"
REVIEWER_VERSION = importlib.metadata.version("agent-sample")

Env = Mapping[str, str]

FORMATS: dict[str, Callable[[], Renderer]] = {
    "text": TextRenderer,
    "json": JsonRenderer,
    "pr-comments": PullRequestCommentsRenderer,
}
# Provedor de PR: (config, ambiente, transporte opcional) -> PullRequestHost.
PROVIDERS: dict[
    str, Callable[[ReviewerConfig, Env, httpx.AsyncBaseTransport | None], PullRequestHost]
] = {
    "github": lambda config, env, transport: PullRequestPublisher(
        GitHubPullRequests(
            RestClient(
                env.get("GITHUB_API_URL", "https://api.github.com"),
                config.allowed_hosts,
                env.get("GITHUB_TOKEN") or None,
                transport=transport,
            )
        )
    ),
}
# Framework da etapa agêntica: (gateway, motivo de indisponibilidade) -> AgentReviewer.
AGENTS: dict[str, Callable[[ModelGateway, str | None], AgentReviewer]] = {
    "deepagents": DeepAgentsReviewer,
}


class Composition:
    def __init__(
        self,
        config: ReviewerConfig,
        catalog: PluginCatalog,
        agent: AgentReviewer,
        hosts: tuple[PullRequestHost, ...],
    ) -> None:
        self.config = config
        self.catalog = catalog
        self._agent = agent
        self._hosts = hosts

    def context(self, options: ReviewOptions) -> ReviewContext:
        return ReviewContext(
            revisions=GitRevisionSource(),
            hosts=self._hosts,
            readers=RepositoryReaders(),
            agent=self._agent,
            capabilities=self.catalog.select(options.plugins, options.skills),
            renderer=_choose("format", options.format, FORMATS)(),
            limits=self.config.limits,
        )


def _choose[T](kind: str, name: str, registry: dict[str, T]) -> T:
    if name not in registry:
        raise UnknownOption(kind, name, tuple(registry))
    return registry[name]


def gateway_from_env(env: Env) -> tuple[ModelGateway, str | None]:
    api_key = env.get("MODEL_API_KEY", "")
    if not api_key:
        reason = "MODEL_API_KEY is not set"
        return UnconfiguredGateway(reason), reason
    gateway = OpenAICompatibleGateway(
        base_url=env.get("MODEL_BASE_URL", "https://api.openai.com/v1"),
        api_key=api_key,
        model=env.get("MODEL_NAME", "gpt-4o-mini"),
    )
    return gateway, None


def load_settings(env: Env) -> tuple[ReviewerConfig, Path]:
    home = Path(env.get("HOME", str(Path.home())))
    user = (
        Path(env.get("XDG_CONFIG_HOME", str(home / ".config"))) / "agent-sample" / "reviewer.toml"
    )
    project = Path(env.get("REVIEWER_CONFIG", "reviewer.toml"))
    cache = Path(env.get("XDG_CACHE_HOME", str(home / ".cache"))) / "agent-sample" / "git"
    return load_config(builtin_source(BUILTIN_PLUGINS), user, project), cache


def bootstrap(
    env: Env = os.environ,
    gateway: ModelGateway | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ReviewService:
    """Carrega e valida configuração, lock, plugins e padrões antes de qualquer revisão."""
    config, cache = load_settings(env)
    catalog = load_catalog(config, REVIEWER_VERSION, cache)
    if gateway is None:
        gateway, unavailable = gateway_from_env(env)
    else:
        unavailable = None
    agent = _choose("agent", env.get("REVIEW_AGENT", "deepagents"), AGENTS)(gateway, unavailable)
    hosts = tuple(factory(config, env, transport) for factory in PROVIDERS.values())
    composition = Composition(config, catalog, agent, hosts)
    defaults = ReviewOptions().merge(
        mode=env.get("REVIEW_MODE"),
        format=env.get("REVIEW_FORMAT"),
    )
    return ReviewService(composition.context, SequentialEngine(), catalog, defaults)


def lock(scopes: tuple[str, ...], env: Env = os.environ) -> list[str]:
    config, cache = load_settings(env)
    return lock_sources(config, REVIEWER_VERSION, cache, scopes)


def cli_main() -> None:
    from agent_sample.application.cli.app import run

    run(bootstrap, lock)


def a2a_main() -> None:
    from agent_sample.application.a2a.server import serve

    try:
        service = bootstrap()
    except ReviewError as exc:
        print(error_message(exc), file=sys.stderr)
        raise SystemExit(2) from None
    serve(service, REVIEWER_VERSION)
