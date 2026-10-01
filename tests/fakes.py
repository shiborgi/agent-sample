import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from agent_sample.composition import BUILTIN_PLUGINS, bootstrap
from agent_sample.domain.capabilities import CapabilitySet
from agent_sample.domain.change import InlineDiff, PullRequestContext
from agent_sample.domain.model import ProposedFinding, Review
from agent_sample.domain.plan import AgentTask
from agent_sample.domain.policy import Limits
from agent_sample.domain.ports import AgentOutcome, ToolCatalog, ToolSpec
from agent_sample.domain.workflow import ReviewContext, ReviewRequest, ReviewState, run_review
from agent_sample.infrastructure.model.ports import ChatMessage, Completion, ToolCall
from agent_sample.infrastructure.output.text import TextRenderer
from agent_sample.infrastructure.plugins.format import load_plugin
from agent_sample.infrastructure.repository.git import GitRevisionSource
from agent_sample.infrastructure.repository.worktree import RepositoryReaders
from agent_sample.infrastructure.workflow.sequential import SequentialEngine

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

SOURCE_DIFF = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,5 @@
 def average(items):
-    return sum(items)
+    token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB"
+    total = sum(items)
+    return total / len(items)

"""


def builtin_capabilities() -> CapabilitySet:
    return CapabilitySet(
        (load_plugin(BUILTIN_PLUGINS / "code-review" / "1.0.0", "builtin", "1.0.0"),)
    )


def proposal(**changes: Any) -> ProposedFinding:
    base: dict[str, Any] = {
        "file": "src/app.py",
        "start_line": 4,
        "end_line": 4,
        "severity": "major",
        "category": "correctness",
        "description": "division by zero when items is empty",
        "suggestion": "return 0 for an empty list",
        "evidence": "return total / len(items)",
        "reviewer": "code-review:python-reviewer",
        "skill": "code-review:python-practices@1.0.0",
    }
    return ProposedFinding(**(base | changes))


class FakeAgent:
    """Agente falso: devolve achados fixos, pode carregar uma skill e pode falhar."""

    name = "fake"

    def __init__(
        self,
        proposed: tuple[ProposedFinding, ...] = (),
        error: Exception | None = None,
        unavailable: str | None = None,
        skill: str | None = "python-practices",
    ) -> None:
        self._proposed = proposed
        self._error = error
        self._unavailable = unavailable
        self._skill = skill
        self.tasks: list[AgentTask] = []

    def unavailable(self) -> str | None:
        return self._unavailable

    async def review(self, task: AgentTask, tools: ToolCatalog, limits: Limits) -> AgentOutcome:
        del limits
        self.tasks.append(task)
        if self._skill:
            await tools.call("load_skill", {"name": self._skill})
        if self._error is not None:
            raise self._error
        reviewers = tuple(dict.fromkeys(item.reviewer for item in self._proposed))
        return AgentOutcome(self._proposed, ("lead", *reviewers))


class FakeHost:
    name = "fake-host"

    def __init__(self, diff: str = SOURCE_DIFF) -> None:
        self.diff = diff
        self.published: list[tuple[str, Review]] = []

    def handles(self, locator: str) -> bool:
        return locator.startswith("fake/")

    async def get_change(self, locator: str) -> str:
        del locator
        return self.diff

    async def get_context(self, locator: str) -> PullRequestContext:
        return PullRequestContext(title=f"PR {locator}", description="adds average")

    async def publish(self, locator: str, review: Review) -> str:
        self.published.append((locator, review))
        return f"posted to {locator}"


def context(
    agent: Any = None,
    hosts: tuple[Any, ...] = (),
    limits: Limits = Limits(),
    capabilities: CapabilitySet | None = None,
) -> ReviewContext:
    return ReviewContext(
        revisions=GitRevisionSource(),
        hosts=hosts,
        readers=RepositoryReaders(),
        agent=agent or FakeAgent(),
        capabilities=capabilities or builtin_capabilities(),
        renderer=TextRenderer(),
        limits=limits,
    )


def review(
    diff: str = SOURCE_DIFF,
    mode: str = "hybrid",
    ctx: ReviewContext | None = None,
    **request: Any,
) -> ReviewState:
    ref = request.pop("ref", InlineDiff(diff))
    wanted = ReviewRequest(ref, mode, **request)  # type: ignore[arg-type]
    return asyncio.run(run_review(wanted, ctx or context(), SequentialEngine()))


def isolated_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    """Ambiente sem configuração de usuário nem de projeto e sem credencial de modelo."""
    return {
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "REVIEWER_CONFIG": str(tmp_path / "missing.toml"),
        **extra,
    }


def isolated_service(tmp_path: Path, **kwargs: Any) -> Any:
    env = kwargs.pop("env", None) or isolated_env(tmp_path)
    return bootstrap(env, **kwargs)


class ScriptedGateway:
    """Modelo falso para o Deep Agents: segue um roteiro de respostas por papel do agente."""

    def __init__(self, script: Any) -> None:
        self._script = script
        self.calls: list[tuple[tuple[ChatMessage, ...], tuple[ToolSpec, ...]]] = []

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] = (),
    ) -> Completion:
        self.calls.append((tuple(messages), tuple(tools)))
        result = self._script(tuple(messages), tuple(tools))
        if asyncio.iscoroutine(result):
            result = await result
        return result


def answer(*findings: dict[str, Any]) -> Completion:
    return Completion(text=json.dumps({"findings": list(findings)}))


def call(name: str, arguments: dict[str, Any], call_id: str = "call-1") -> Completion:
    return Completion(text="", tool_calls=(ToolCall(id=call_id, name=name, arguments=arguments),))
