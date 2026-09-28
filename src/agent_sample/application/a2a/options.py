from typing import Any

from agent_sample.application.service import Options
from agent_sample.domain.errors import UnknownOption


def request_options[O: Options](
    metadata: dict[str, Any],
    defaults: O,
    keys: tuple[str, ...],
    lists: tuple[str, ...] = (),
) -> O:
    """Opções por requisição vêm de `metadata`; o que faltar segue o padrão do servidor.

    Só as chaves listadas são lidas; as de `lists` aceitam uma lista ou texto separado por vírgula.
    """
    changes: dict[str, object] = {}
    for key in keys:
        value = metadata.get(key)
        if value is None:
            continue
        if key in lists:
            items = value.split(",") if isinstance(value, str) else value
            if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
                raise UnknownOption(f"{key} value", repr(value), ("a list of strings",))
            changes[key] = tuple(item.strip() for item in items if item.strip())
        elif not isinstance(value, str):
            raise UnknownOption(f"{key} value", repr(value), ("a string",))
        else:
            changes[key] = value
    return defaults.merge(**changes)
