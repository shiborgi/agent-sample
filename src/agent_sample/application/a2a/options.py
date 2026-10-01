from typing import Any

from agent_sample.application.service import ReviewOptions
from agent_sample.domain.change import ChangeRef, InlineDiff, PullRequest, RevisionRange
from agent_sample.domain.model import UnknownOption

TEXT_KEYS = ("mode", "language", "format")
LIST_KEYS = ("focus", "plugins", "skills")


def request_options(metadata: dict[str, Any], defaults: ReviewOptions) -> ReviewOptions:
    """Opções por requisição vêm de `metadata`; o que faltar segue o padrão do servidor."""
    changes: dict[str, object] = {}
    for key in TEXT_KEYS:
        value = metadata.get(key)
        if value is not None:
            changes[key] = _text(key, value)
    for key in LIST_KEYS:
        value = metadata.get(key)
        if value is not None:
            items = value.split(",") if isinstance(value, str) else value
            if not isinstance(items, list):
                raise UnknownOption(f"{key} value", repr(value), ("a list of strings",))
            changes[key] = tuple(_text(key, item).strip() for item in items if str(item).strip())
    post = metadata.get("post")
    if post is not None:
        if not isinstance(post, bool):
            raise UnknownOption("post value", repr(post), ("true", "false"))
        changes["post"] = post
    return defaults.merge(**changes)


def request_ref(text: str, metadata: dict[str, Any]) -> ChangeRef:
    """A mudança vem no texto (diff) ou como referência em metadata."""
    repository = metadata.get("repository")
    repository = _text("repository", repository) if repository is not None else None
    if metadata.get("pull_request") is not None:
        return PullRequest(_text("pull_request", metadata["pull_request"]), repository)
    if metadata.get("base") is not None or metadata.get("head") is not None:
        base = metadata.get("base")
        head = metadata.get("head")
        if base is None or head is None:
            raise UnknownOption(
                "revision range", repr({"base": base, "head": head}), ("both base and head",)
            )
        return RevisionRange(repository or ".", _text("base", base), _text("head", head))
    return InlineDiff(text, repository)


def _text(key: str, value: Any) -> str:
    if not isinstance(value, str):
        raise UnknownOption(f"{key} value", repr(value), ("a string",))
    return value
