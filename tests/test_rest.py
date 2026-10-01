"""Cliente REST e provedor GitHub contra um servidor falso (httpx.MockTransport), sem rede."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from agent_sample.application.cli.app import build_app
from agent_sample.composition import bootstrap, lock
from agent_sample.domain.model import ChangeNotFound, RemoteError
from agent_sample.infrastructure.rest.client import RestClient
from agent_sample.infrastructure.rest.github import GitHubPullRequests, PullRequestPublisher
from tests.fakes import SOURCE_DIFF, isolated_env

TOKEN = "ghs_supersecrettoken"
API = "https://api.github.com"


class FakeGitHub:
    """Servidor falso: responde o PR 7 de acme/shop e registra as requisições."""

    def __init__(self, failures: list[int] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.failures = failures or []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failures:
            return httpx.Response(self.failures.pop(0))
        path = request.url.path
        if request.method == "POST" and path == "/repos/acme/shop/pulls/7/reviews":
            return httpx.Response(
                200, json={"id": 1, "html_url": "https://github.com/acme/shop/pull/7#review-1"}
            )
        if path == "/repos/acme/shop/pulls/7":
            if request.headers["Accept"] == "application/vnd.github.diff":
                return httpx.Response(200, text=SOURCE_DIFF)
            return httpx.Response(
                200,
                json={"title": "Average", "body": "Fixes #12", "head": {"sha": "abc123"}},
            )
        if path == "/repos/acme/shop/commits/abc123/status":
            return httpx.Response(200, json={"state": "success"})
        if path == "/repos/acme/shop/issues/7/comments":
            return httpx.Response(
                200, json=[{"user": {"login": "ana"}, "body": "please add tests"}]
            )
        if path == "/repos/acme/shop/issues/12":
            return httpx.Response(200, json={"title": "average crashes"})
        return httpx.Response(404)

    @property
    def paths(self) -> list[str]:
        return [f"{r.method} {r.url.path}" for r in self.requests]


def client(
    server: FakeGitHub, hosts: tuple[str, ...] = ("api.github.com",), **kwargs
) -> RestClient:
    sleeps: list[float] = kwargs.pop("sleeps", [])

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    return RestClient(
        API, hosts, TOKEN, transport=httpx.MockTransport(server), sleep=sleep, **kwargs
    )


def test_gets_the_pull_request_change_and_context() -> None:
    server = FakeGitHub()
    github = PullRequestPublisher(GitHubPullRequests(client(server)))
    assert github.handles("https://github.com/acme/shop/pull/7")
    assert github.handles("acme/shop#7")
    assert asyncio.run(github.get_change("acme/shop#7")) == SOURCE_DIFF
    context = asyncio.run(github.get_context("https://github.com/acme/shop/pull/7"))
    assert context.title == "Average"
    assert context.ci_status == "success"
    assert context.linked_issues == ("#12 average crashes",)
    assert context.comments == ("ana: please add tests",)
    assert server.requests[0].headers["Authorization"] == f"Bearer {TOKEN}"


def test_partial_context_degrades_into_notices_instead_of_failing() -> None:
    server = FakeGitHub()

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(("/status", "/comments")):
            return httpx.Response(503)
        return server(request)

    github = PullRequestPublisher(GitHubPullRequests(client(flaky)))
    context = asyncio.run(github.get_context("https://github.com/acme/shop/pull/7"))
    assert context.title == "Average"
    assert context.ci_status == "unknown"
    assert context.comments == ()
    assert context.linked_issues == ("#12 average crashes",)
    assert any("CI status" in notice for notice in context.notices)
    assert any("comments" in notice for notice in context.notices)


def test_authentication_error_is_translated_without_leaking_the_token() -> None:
    github = PullRequestPublisher(GitHubPullRequests(client(FakeGitHub(failures=[401]))))
    with pytest.raises(RemoteError, match="authentication failed") as error:
        asyncio.run(github.get_change("acme/shop#7"))
    assert TOKEN not in str(error.value)


def test_transient_errors_are_retried_a_limited_number_of_times() -> None:
    sleeps: list[float] = []
    server = FakeGitHub(failures=[503, 502])
    github = PullRequestPublisher(GitHubPullRequests(client(server, sleeps=sleeps)))
    assert asyncio.run(github.get_change("acme/shop#7")) == SOURCE_DIFF
    assert sleeps == [0.5, 1.0]
    server = FakeGitHub(failures=[503, 503, 503, 503])
    with pytest.raises(RemoteError, match="HTTP 503"):
        asyncio.run(
            PullRequestPublisher(GitHubPullRequests(client(server))).get_change("acme/shop#7")
        )
    assert len(server.requests) == 3


def test_client_errors_are_not_retried() -> None:
    server = FakeGitHub(failures=[404])
    with pytest.raises(ChangeNotFound):
        asyncio.run(
            PullRequestPublisher(GitHubPullRequests(client(server))).get_change("acme/shop#7")
        )
    assert len(server.requests) == 1


def test_connection_errors_are_retried_then_reported() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    rest = RestClient(
        API, ("api.github.com",), None, transport=httpx.MockTransport(broken), sleep=_no_sleep
    )
    with pytest.raises(RemoteError, match="ConnectError"):
        asyncio.run(rest.request("GET", "/repos/acme/shop/pulls/7"))


async def _no_sleep(seconds: float) -> None:
    del seconds


def test_hosts_outside_the_allow_list_are_refused_before_any_request() -> None:
    server = FakeGitHub()
    with pytest.raises(RemoteError, match="host not allowed: api.github.com"):
        asyncio.run(
            PullRequestPublisher(
                GitHubPullRequests(client(server, hosts=("ghe.internal",)))
            ).get_change("acme/shop#7")
        )
    assert server.requests == []


def run_cli(tmp_path: Path, server: FakeGitHub, *args: str):
    env = isolated_env(tmp_path, GITHUB_TOKEN=TOKEN)
    app = build_app(
        lambda: bootstrap(env, transport=httpx.MockTransport(server)), lambda s: lock(s, env)
    )
    return CliRunner().invoke(app, ["review", *args])


def test_cli_publishes_only_with_post(tmp_path: Path) -> None:
    server = FakeGitHub()
    result = run_cli(tmp_path, server, "--pr", "acme/shop#7")
    assert result.exit_code == 1, result.output
    assert not any(path.startswith("POST") for path in server.paths)
    assert "source: github acme/shop#7" in result.output
    assert TOKEN not in result.output

    result = run_cli(tmp_path, server, "--pr", "acme/shop#7", "--post", "--format", "json")
    assert result.exit_code == 1, result.output
    posts = [r for r in server.requests if r.method == "POST"]
    assert len(posts) == 1
    body = json.loads(posts[0].content)
    assert body["event"] == "REQUEST_CHANGES"
    assert body["comments"][0]["path"] == "src/app.py"
    assert body["comments"][0]["line"] == 2
    assert TOKEN not in result.output
    assert "posted: https://github.com/acme/shop/pull/7#review-1" in result.output


def test_cli_refuses_post_without_a_pull_request(tmp_path: Path) -> None:
    result = run_cli(tmp_path, FakeGitHub(), "--diff", SOURCE_DIFF, "--post")
    assert result.exit_code == 2
    assert "cannot publish" in result.output
