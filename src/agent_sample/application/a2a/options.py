from typing import Any

from agent_sample.application.service import ClassifyOptions
from agent_sample.domain.model import UnknownOption

KEYS = ("strategy", "engine", "agent", "prompt_version")


def request_options(metadata: dict[str, Any], defaults: ClassifyOptions) -> ClassifyOptions:
    """Opções por requisição vêm de `metadata`; o que faltar segue o padrão do servidor."""
    changes: dict[str, str] = {}
    for key in KEYS:
        value = metadata.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise UnknownOption(f"{key} value", repr(value), ("a string",))
        changes[key] = value
    return defaults.merge(**changes)
