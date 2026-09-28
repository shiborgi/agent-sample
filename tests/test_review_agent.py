import asyncio
import json
import logging
from pathlib import Path

import pytest

from agent_sample.application.review import ReviewOptions
from agent_sample.domain.content import REVIEW_TASK
from agent_sample.domain.errors import AgentAttemptFailed, AgentFailed
from agent_sample.domain.review.change import prepare_change
from agent_sample.domain.review.model import RepositoryError, Review
from agent_sample.domain.review.ports import Repository, SearchHit
from agent_sample.domain.review.strategies import AgentReviewer, HybridReviewer, WorkflowReviewer
from agent_sample.domain.review.tools import REVIEW_TOOLS, ReviewContext
from agent_sample.domain.tools import Toolbox
from agent_sample.infrastructure.agents.answer import parse_review
from agent_sample.infrastructure.content.files import FileContentLibrary
from agent_sample.infrastructure.repository.local import LocalRepository
from agent_sample.infrastructure.workflow.sequential import SequentialEngine
from tests.fakes import (
    CONTENT_ROOT,
    FixedReviewAgent,
    ScriptedReviewGateway,
    composition,
    proposal,
)

CONTENT = FileContentLibrary(CONTENT_ROOT)
SECRET = 'API_KEY = "9f8e7d6c5b4a39281706"'
DIFF = f"""\
--- a/app/pricing.py
+++ b/app/pricing.py
@@ -1,2 +1,4 @@
 def average(values):
-    return sum(values)
+    total = sum(values)
+    return total / len(values)
+{SECRET}
"""


def agent_reviewer(
    agent: FixedReviewAgent, repository: Repository | None = None, part_chars: int = 30_000
) -> AgentReviewer:
    skills = tuple(CONTENT.skill(name) for name in CONTENT.offered_skills(REVIEW_TASK))
    prompt = CONTENT.prompt(REVIEW_TASK.prompt)
    return AgentReviewer(agent, prompt, skills, repository, part_chars)


def hybrid(agent: FixedReviewAgent) -> HybridReviewer:
    return HybridReviewer(WorkflowReviewer(SequentialEngine()), agent_reviewer(agent))


def run(reviewer: object, text: str = DIFF) -> Review:
    return asyncio.run(reviewer.review(prepare_change(text)))  # type: ignore[attr-defined]


def discards(review: Review) -> list[str]:
    return [step.detail for step in review.trace if step.outcome == "discarded"]


def test_agent_findings_outside_the_diff_are_discarded_and_recorded() -> None:
    agent = FixedReviewAgent(
        (
            proposal(start=3),
            proposal(path="app/other.py"),
            proposal(start=9),
            proposal(start=3, end=2),
            proposal(severity="blocker"),
            proposal(category="bugs"),
            proposal(description="  "),
            proposal(start=None),
        )
    )
    review = run(agent_reviewer(agent))
    (accepted,) = review.findings
    assert (accepted.start, accepted.origin, accepted.source) == (3, "agent", "agent:fixed")
    assert accepted.evidence == "+    return total / len(values)"
    assert discards(review) == [
        "app/other.py:2 — arquivo fora do diff revisado: app/other.py",
        "app/pricing.py:9 — linha 9..9 não existe no código novo do diff",
        "app/pricing.py:3 — intervalo de linhas inválido: 3..2",
        "app/pricing.py:2 — severidade inválida: blocker",
        "app/pricing.py:2 — categoria inválida: bugs",
        "app/pricing.py:2 — achado sem descrição",
        "app/pricing.py:? — intervalo de linhas inválido: None..None",
    ]


def test_agent_cannot_remove_or_downgrade_a_critical_rule_finding() -> None:
    downgrade = proposal(start=4, severity="nit", category="security", description="ok")
    for agent in (FixedReviewAgent(), FixedReviewAgent((downgrade,))):
        review = run(hybrid(agent))
        secrets = [item for item in review.findings if item.category == "security"]
        assert [(item.severity, item.origin) for item in secrets] == [("critical", "rule")]
        assert review.decision == "request_changes"


def test_duplicated_findings_appear_once() -> None:
    same_as_rule = proposal(start=2, severity="minor", category="tests")
    repeated = proposal(start=3)
    review = run(hybrid(FixedReviewAgent((same_as_rule, repeated, repeated))))
    assert [(item.category, item.origin) for item in review.findings] == [
        ("security", "rule"),
        ("correctness", "agent"),
        ("tests", "rule"),
    ]
    duplicates = [step for step in review.trace if step.name == "duplicate"]
    assert len(duplicates) == 2
    assert "duplica minor/tests de rule:missing-tests" in duplicates[0].detail


def test_agent_failure_keeps_rule_findings_and_records_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    agent = FixedReviewAgent(error=RuntimeError("offline"))
    with caplog.at_level(logging.WARNING):
        review = run(hybrid(agent))
    assert [item.source for item in review.findings] == ["rule:secrets", "rule:missing-tests"]
    assert review.reviewed_by == "workflow:sequential"
    failed, fallback = [step for step in review.trace if step.kind in ("agent", "fallback")]
    assert (failed.outcome, fallback.name) == ("failed", "rules-only")
    assert "offline" in failed.detail
    assert "O agente falhou" in review.summary
    assert "fell back to rules only" in caplog.text


def test_agent_alone_reports_its_failure() -> None:
    with pytest.raises(AgentAttemptFailed, match="agent:fixed failed: fixed: boom") as info:
        run(agent_reviewer(FixedReviewAgent(error=AgentFailed("fixed", "boom"))))
    assert info.value.step.detail == "parte 1/1 (app/pricing.py): fixed: boom"


def test_trace_records_prompt_version_and_loaded_skills() -> None:
    review = run(hybrid(FixedReviewAgent(load=("security-review", "test-quality"))))
    (step,) = [step for step in review.trace if step.kind == "agent"]
    assert step.prompt == "review_change@v1"
    assert step.skills == ("security-review@v1", "test-quality@v1")
    assert review.reviewed_by == "hybrid(workflow:sequential->agent:fixed)"


def test_agent_receives_the_rule_findings_and_the_focus() -> None:
    agent = FixedReviewAgent()
    asyncio.run(hybrid(agent).review(prepare_change(DIFF, focus=("performance",))))
    (request,) = agent.requests
    assert "Foco pedido: performance." in request.text
    assert "app/pricing.py:4-4 critical/security" in request.text
    assert request.max_tool_rounds == 8


def test_large_diffs_are_reviewed_in_parts_and_joined() -> None:
    other = "--- a/app/b.py\n+++ b/app/b.py\n@@ -0,0 +1 @@\n+b = 1\n"
    agent = FixedReviewAgent((proposal(start=3), proposal(path="app/b.py", start=1)))
    review = run(agent_reviewer(agent, part_chars=len(DIFF)), DIFF + other)
    assert [("app/b.py" in request.text) for request in agent.requests] == [False, True]
    assert sorted(item.path for item in review.findings) == ["app/b.py", "app/pricing.py"]
    parts = [step.detail for step in review.trace if step.kind == "agent"]
    assert [detail.split(":")[0] for detail in parts] == [
        "parte 1/2 (app/pricing.py)",
        "parte 2/2 (app/b.py)",
    ]


def test_agent_is_skipped_when_nothing_is_reviewable() -> None:
    agent = FixedReviewAgent()
    binary = "diff --git a/logo.png b/logo.png\nBinary files a/logo.png and b/logo.png differ\n"
    review = run(hybrid(agent), binary)
    assert agent.requests == []
    assert review.decision == "approve"
    assert [item.path for item in review.unreviewed] == ["logo.png"]


# --- ferramentas ---------------------------------------------------------------------------


class SpyRepository:
    def __init__(self) -> None:
        self.reads: list[str] = []

    def read(self, path: str) -> str:
        self.reads.append(path)
        raise RepositoryError(f"file not found: {path}")

    def search(self, text: str, limit: int) -> tuple[SearchHit, ...]:
        del text, limit
        return ()


def call(repository: Repository | None, name: str, **arguments: object) -> str:
    toolbox = Toolbox(ReviewContext((), repository), REVIEW_TOOLS)
    return asyncio.run(toolbox.call(name, arguments))


@pytest.mark.parametrize("path", ["../secret.txt", "/etc/passwd", "a/../../x", "~/x", "C:/x"])
def test_domain_refuses_paths_outside_before_touching_the_repository(path: str) -> None:
    spy = SpyRepository()
    assert call(spy, "read_repo_file", path=path).startswith("erro: caminho fora do repositório")
    assert spy.reads == []


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    (root / "app" / "pricing.py").write_text("".join(f"linha {n}\n" for n in range(1, 301)))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("segredo fora do repo\n")
    (root / "link.txt").symlink_to(outside / "secret.txt")
    (root / "linkdir").symlink_to(outside, target_is_directory=True)
    return root


def test_tools_never_read_outside_the_repository(repo: Path) -> None:
    repository = LocalRepository(repo)
    for path in ("link.txt", "linkdir/secret.txt"):
        assert call(repository, "read_repo_file", path=path) == (
            f"erro: path outside the repository: {path}"
        )
    with pytest.raises(RepositoryError, match="outside"):
        repository.read("../outside/secret.txt")
    assert call(repository, "search_repo", text="segredo") == "nenhuma ocorrência"


def test_read_tool_returns_a_numbered_bounded_excerpt(repo: Path) -> None:
    repository = LocalRepository(repo)
    excerpt = call(repository, "read_repo_file", path="app/pricing.py", start_line=10, end_line=12)
    assert excerpt == "10: linha 10\n11: linha 11\n12: linha 12"
    whole = call(repository, "read_repo_file", path="app/pricing.py")
    assert whole.splitlines()[-1] == "200: linha 200"
    assert call(repository, "read_repo_file", path="app/pricing.py", start_line=0).startswith(
        "erro: start_line"
    )
    assert call(repository, "read_repo_file", path="nope.py") == "erro: file not found: nope.py"
    hits = call(repository, "search_repo", text="linha 29")
    assert hits.splitlines()[0] == "app/pricing.py:29: linha 29"


def test_tools_without_a_repository_say_so() -> None:
    message = "erro: repositório indisponível nesta revisão; use só o diff"
    assert call(None, "read_repo_file", path="app.py") == message
    assert call(None, "search_repo", text="x = 1") == message


def test_list_criteria_shows_the_index_only() -> None:
    skills = tuple(CONTENT.skill(name) for name in CONTENT.offered_skills(REVIEW_TASK))
    toolbox = Toolbox(ReviewContext(skills, None), REVIEW_TOOLS)
    payload = json.loads(asyncio.run(toolbox.call("list_criteria", {})))
    assert payload["severities"] == ["critical", "major", "minor", "nit"]
    assert {skill["name"] for skill in payload["skills"]} == {
        "python-practices",
        "security-review",
        "test-quality",
    }
    assert toolbox.loaded_skills == ()


# --- leitura da resposta e agentes reais ---------------------------------------------------


def test_review_answer_is_read_by_the_infrastructure() -> None:
    answer = parse_review(
        'ok {"summary": "s", "findings": [{"path": "a.py", "start_line": "3", '
        '"severity": "minor", "category": "style", "description": "d"}, 7]}',
        "fake",
    )
    first, second = answer.findings
    assert (first.path, first.start, first.end, first.severity) == ("a.py", 3, None, "minor")
    assert (second.path, second.start, second.description) == ("", None, "")
    with pytest.raises(AgentFailed, match="not a review"):
        parse_review("sem json", "fake")
    with pytest.raises(AgentFailed, match="not a review"):
        parse_review('{"findings": "nenhum"}', "fake")


@pytest.mark.parametrize("agent", ["langgraph", "deepagents"])
def test_real_agents_investigate_with_tools_and_propose_findings(agent: str, repo: Path) -> None:
    finding = {
        "path": "app/pricing.py",
        "start_line": 3,
        "end_line": 3,
        "severity": "major",
        "category": "correctness",
        "description": "len(values) pode ser zero",
        "suggestion": "trate lista vazia",
    }
    gateway = ScriptedReviewGateway(findings=[finding])
    options = ReviewOptions(strategy="agent", agent=agent, repo=str(repo))
    review = run(composition(gateway).reviewer(options))
    (accepted,) = review.findings
    assert (accepted.start, accepted.source) == (3, f"agent:{agent}")
    (step,) = [step for step in review.trace if step.kind == "agent"]
    assert (step.prompt, step.skills) == ("review_change@v1", ("python-practices@v1",))
    messages, tools = gateway.calls[0]
    system = next(message.content for message in messages if message.role == "system")
    assert "- security-review: Critérios de segurança" in system
    assert "# Revisão de segurança" not in system
    assert "qualquer achado critical ou major → request_changes" in system
    assert {"read_repo_file", "search_repo", "list_criteria", "load_skill"} <= {
        tool.name for tool in tools
    }
    results = [message.content for message in gateway.calls[-1][0] if message.role == "tool"]
    assert any(content.startswith("1: linha 1") for content in results)


def test_agent_findings_never_repeat_a_secret() -> None:
    leaky = proposal(start=4, description='a chave "9f8e7d6c5b4a39281706" ficou no código')
    agent = FixedReviewAgent((leaky,), summary="vazou 9f8e7d6c5b4a39281706")
    review = run(agent_reviewer(agent))
    (finding,) = review.findings
    assert "9f8e7d6c5b4a39281706" not in finding.evidence + finding.description + review.summary
    assert finding.evidence == '+API_KEY = "9f8e****"'
