import asyncio
import json
from pathlib import Path

import pytest

from agent_sample.application.service import ClassifyOptions
from agent_sample.domain.content import CLASSIFY_TASK
from agent_sample.domain.model import ContentError
from agent_sample.infrastructure.content.files import FileContentLibrary
from tests.fakes import CONTENT_ROOT, ScriptedGateway, composition, copy_content


def test_shipped_content_is_valid_and_published() -> None:
    library = FileContentLibrary(CONTENT_ROOT)
    library.require(CLASSIFY_TASK)
    assert all(item.published for item in (*library.prompts(), *library.skills()))
    assert library.prompt("classify_subject").version == "v2"


def test_editing_a_published_version_is_rejected(tmp_path: Path) -> None:
    root = copy_content(tmp_path)
    path = root / "prompts/classify_subject/v1.md"
    path.write_text(path.read_text() + "\nmudança silenciosa\n")
    with pytest.raises(ContentError, match="published version changed"):
        FileContentLibrary(root)


def test_draft_is_selectable_but_never_the_default(tmp_path: Path) -> None:
    root = copy_content(tmp_path)
    (root / "prompts/classify_subject/v3.md").write_text("Rascunho.\n$subjects\n$skills\n")
    library = FileContentLibrary(root)
    assert library.prompt("classify_subject").version == "v2"
    draft = library.prompt("classify_subject", "v3")
    assert not draft.published


def test_publish_freezes_a_version(tmp_path: Path) -> None:
    root = copy_content(tmp_path)
    (root / "skills/out-of-scope/v2.md").write_text("---\ndescription: nova\n---\ncorpo\n")
    library = FileContentLibrary(root)
    digest = library.publish("skill", "out-of-scope", "v2")
    manifest = json.loads((root / "published.json").read_text())
    assert manifest["skills"]["out-of-scope"]["v2"] == digest
    assert FileContentLibrary(root).skill("out-of-scope").version == "v2"
    with pytest.raises(ContentError, match="already published"):
        library.publish("skill", "out-of-scope", "v2")


@pytest.mark.parametrize(
    ("relative", "content", "message"),
    [
        ("skills/out-of-scope/v2.md", "sem frontmatter\n", "frontmatter"),
        ("skills/out-of-scope/v2.md", "---\ntitle: x\n---\ncorpo\n", "description"),
        ("prompts/classify_subject/v3.md", "Olá $cliente\n", "unknown placeholders"),
        ("prompts/classify_subject/final.md", "x\n", "version must look like"),
    ],
)
def test_invalid_content_fails_at_startup(
    tmp_path: Path, relative: str, content: str, message: str
) -> None:
    root = copy_content(tmp_path)
    (root / relative).write_text(content)
    with pytest.raises(ContentError, match=message):
        FileContentLibrary(root)


def test_missing_published_file_fails_at_startup(tmp_path: Path) -> None:
    root = copy_content(tmp_path)
    (root / "skills/out-of-scope/v1.md").unlink()
    with pytest.raises(ContentError, match="missing"):
        FileContentLibrary(root)


def test_skill_required_by_the_task_must_exist(tmp_path: Path) -> None:
    root = copy_content(tmp_path)
    for path in (root / "skills/subject-boundaries").iterdir():
        path.unlink()
    manifest = json.loads((root / "published.json").read_text())
    del manifest["skills"]["subject-boundaries"]
    (root / "published.json").write_text(json.dumps(manifest))
    with pytest.raises(ContentError, match="skill not found: subject-boundaries"):
        composition(ScriptedGateway(), root)


def test_unknown_versions_and_pins_are_clear_errors() -> None:
    root = composition(ScriptedGateway())
    with pytest.raises(ContentError, match="no version v9"):
        root.build(ClassifyOptions(strategy="agent", prompt_version="v9"))
    with pytest.raises(ContentError, match="invalid skill pin"):
        root.build(ClassifyOptions(strategy="agent", skills=("nope@v1",)))


def test_pinned_skill_version_reaches_the_trace(tmp_path: Path) -> None:
    root = copy_content(tmp_path)
    (root / "skills/subject-boundaries/v2.md").write_text("---\ndescription: d\n---\nnova\n")
    wired = composition(ScriptedGateway(skill="subject-boundaries"), root)
    options = ClassifyOptions(strategy="agent", skills=("subject-boundaries@v2",))
    verdict = asyncio.run(wired.build(options).classify("Erro na fatura"))
    assert verdict.trace[0].skills == ("subject-boundaries@v2",)
