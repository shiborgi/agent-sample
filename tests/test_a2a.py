from starlette.applications import Starlette

from agent_sample.application.a2a.server import build_server
from tests.fakes import FixedClassifier


def test_a2a_server_uses_the_domain_classifier() -> None:
    app = build_server(FixedClassifier("billing"), "http://127.0.0.1:9999")
    assert isinstance(app, Starlette)
