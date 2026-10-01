"""Pull requests do GitHub: obter diff (etapa 1), contexto (degradável) e publicar (etapa 9).

A classe `PullRequestPublisher` aceita qualquer `_PullRequestProvider`, então adicionar outro
provedor (ex.: GitLab) é escrever outro `_PullRequestProvider` e registrar na composição.
"""

import re
from dataclasses import dataclass
from typing import Protocol

from agent_sample.domain.change import PullRequestContext
from agent_sample.domain.model import RemoteError, Review, UnknownOption
from agent_sample.infrastructure.output.pr_comments import comment_body, review_body
from agent_sample.infrastructure.rest.client import RestClient

URL = re.compile(r"https://github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)/?")
SHORT = re.compile(r"([\w.-]+)/([\w.-]+)#(\d+)")
LINKED = re.compile(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)")
EVENTS = {"approve": "APPROVE", "comment": "COMMENT", "request_changes": "REQUEST_CHANGES"}
MAX_COMMENTS = 20


@dataclass(frozen=True, slots=True)
class Coordinates:
    owner: str
    repo: str
    number: int

    @property
    def base(self) -> str:
        return f"/repos/{self.owner}/{self.repo}"


def coordinates(locator: str) -> Coordinates:
    matched = URL.fullmatch(locator.strip()) or SHORT.fullmatch(locator.strip())
    if matched is None:
        raise UnknownOption("pull request", locator, ("https://github.com/o/r/pull/N", "o/r#N"))
    return Coordinates(matched.group(1), matched.group(2), int(matched.group(3)))


class _PullRequestProvider(Protocol):
    """Operações REST de um provedor de pull requests, em termos de coordenadas do provedor."""

    name: str

    def parse(self, locator: str) -> Coordinates: ...

    async def request(
        self, method: str, path: str, *, accept: str = ..., json: dict | None = ...
    ): ...

    def base(self, coordinates: Coordinates) -> str: ...


class GitHubPullRequests:
    """Implementação `_PullRequestProvider` para o GitHub."""

    name = "github"

    def __init__(self, client: RestClient) -> None:
        self._client = client

    def parse(self, locator: str) -> Coordinates:
        return coordinates(locator)

    def base(self, coordinates: Coordinates) -> str:
        return coordinates.base

    async def request(
        self,
        method: str,
        path: str,
        *,
        accept: str = "application/vnd.github+json",
        json: dict | None = None,
    ):
        return await self._client.request(method, path, accept=accept, json=json)


class PullRequestPublisher:
    """Publica a revisão como comentários no PR via qualquer provedor de pull request."""

    name = "github"

    def __init__(self, provider: _PullRequestProvider) -> None:
        self._provider = provider
        self.name = provider.name

    def handles(self, locator: str) -> bool:
        return bool(URL.fullmatch(locator.strip()) or SHORT.fullmatch(locator.strip()))

    async def get_change(self, locator: str) -> str:
        pr = self._provider.parse(locator)
        response = await self._provider.request(
            "GET",
            f"{self._provider.base(pr)}/pulls/{pr.number}",
            accept="application/vnd.github.diff",
        )
        return response.text

    async def get_context(self, locator: str) -> PullRequestContext:
        notices: list[str] = []
        pr = self._provider.parse(locator)
        base = self._provider.base(pr)
        data = await self._optional(
            "GET", f"{base}/pulls/{pr.number}", notices, "pull request", default={}
        )
        body = str(data.get("body") or "")
        title = str(data.get("title") or "")
        sha = str((data.get("head") or {}).get("sha") or "")
        status = "unknown"
        if sha:
            status_data = await self._optional(
                "GET", f"{base}/commits/{sha}/status", notices, "CI status", default={}
            )
            status = str(status_data.get("state") or "unknown")
        else:
            notices.append("pull request: no head sha; CI status unknown")
        comments = await self._optional(
            "GET", f"{base}/issues/{pr.number}/comments", notices, "comments", default=[]
        )
        issues: list[str] = []
        for number in dict.fromkeys(LINKED.findall(body)):
            issue = await self._optional(
                "GET", f"{base}/issues/{number}", notices, f"issue #{number}", default={}
            )
            if issue.get("title"):
                issues.append(f"#{number} {issue['title']}")
        rendered = tuple(
            f"{(item.get('user') or {}).get('login', '?')}: {str(item.get('body') or '')[:300]}"
            for item in comments[:MAX_COMMENTS]
        )
        return PullRequestContext(
            title=title,
            description=body,
            linked_issues=tuple(issues),
            ci_status=status,
            comments=rendered,
            notices=tuple(notices),
        )

    async def publish(self, locator: str, review: Review) -> str:
        pr = self._provider.parse(locator)
        base = self._provider.base(pr)
        comments = []
        for finding in review.findings:
            comment = {
                "path": finding.file,
                "line": finding.end_line,
                "side": "RIGHT",
                "body": comment_body(finding),
            }
            if finding.start_line != finding.end_line:
                comment |= {"start_line": finding.start_line, "start_side": "RIGHT"}
            comments.append(comment)
        response = await self._provider.request(
            "POST",
            f"{base}/pulls/{pr.number}/reviews",
            json={
                "event": EVENTS[review.decision],
                "body": review_body(review),
                "comments": comments,
            },
        )
        data = response.json()
        return str(data.get("html_url") or f"review {data.get('id', '?')}")

    async def _optional(self, method, path, notices, field, default):
        """Contexto parcial degrada em aviso; o diff em si nunca degrada."""
        try:
            response = await self._provider.request(method, path)
            return response.json()
        except RemoteError as exc:
            notices.append(f"{field}: {exc}")
            return default
