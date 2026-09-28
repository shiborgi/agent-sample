import json
from typing import Any

from agent_sample.domain.model import SUBJECTS
from agent_sample.domain.ports import ToolSpec

LIST_SUBJECTS = ToolSpec(
    name="list_subjects",
    description="Lista os assuntos permitidos para classificar a mensagem.",
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
)


def list_subjects_payload() -> str:
    payload = [
        {"id": subject.id, "name": subject.name, "description": subject.description}
        for subject in SUBJECTS
    ]
    return json.dumps(payload, ensure_ascii=False)


class SubjectCatalog:
    def specs(self) -> tuple[ToolSpec, ...]:
        return (LIST_SUBJECTS,)

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        del arguments
        if name != LIST_SUBJECTS.name:
            raise KeyError(name)
        return list_subjects_payload()
