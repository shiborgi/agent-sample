import json
from dataclasses import asdict

from agent_sample.domain.model import Review


class JsonRenderer:
    """Revisão estruturada para integração; chaves ordenadas para saída estável."""

    name = "json"

    def render(self, review: Review) -> str:
        return json.dumps(asdict(review), indent=2, sort_keys=True, ensure_ascii=False)
