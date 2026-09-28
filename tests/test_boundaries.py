import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "agent_sample"
PACKAGE = "agent_sample"

# domain: só biblioteca padrão, e nada que diga onde o conteúdo mora, que leia disco ou rode git.
DOMAIN_BANNED_STDLIB = {
    "os",
    "pathlib",
    "importlib",
    "io",
    "shutil",
    "glob",
    "posixpath",
    "ntpath",
    "subprocess",
    "tempfile",
}
# Executar processos (git) é detalhe de infraestrutura.
INFRA_ONLY_STDLIB = {"subprocess"}
# application: só os protocolos de entrada e saída.
APPLICATION_THIRD_PARTY = {"typer", "a2a", "starlette", "uvicorn"}
# protocolo de chat com o modelo: só a infra conhece.
LLM_PROTOCOL = {"ChatMessage", "Completion", "ModelGateway", "ToolCall"}


def test_domain_only_uses_stdlib_and_itself() -> None:
    for path, modules in _layer("domain"):
        for module in modules:
            top = module.split(".")[0]
            if top == PACKAGE:
                assert module.startswith(f"{PACKAGE}.domain"), f"{path} imports {module}"
            else:
                assert top in sys.stdlib_module_names, f"{path} imports {module}"
                assert top not in DOMAIN_BANNED_STDLIB, f"{path} imports {module}"


def test_domain_does_not_know_the_llm_protocol() -> None:
    """Mensagens de chat, gateway de modelo e renderização de prompt são detalhes da infra."""
    for path in (ROOT / "domain").rglob("*.py"):
        tree = ast.parse(path.read_text())
        names = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
        names |= {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        assert not names & LLM_PROTOCOL, f"{path} knows {names & LLM_PROTOCOL}"
        assert "string" not in _modules(tree), f"{path} renders prompt templates"


def test_application_only_knows_domain_and_protocols() -> None:
    for path, modules in _layer("application"):
        for module in modules:
            top = module.split(".")[0]
            if top == PACKAGE:
                assert module.startswith((f"{PACKAGE}.domain", f"{PACKAGE}.application")), (
                    f"{path} imports {module}"
                )
            else:
                allowed = top in sys.stdlib_module_names or top in APPLICATION_THIRD_PARTY
                assert allowed, f"{path} imports {module}"


def test_infrastructure_does_not_import_application_or_composition() -> None:
    for path, modules in _layer("infrastructure"):
        for module in modules:
            assert not module.startswith((f"{PACKAGE}.application", f"{PACKAGE}.composition")), (
                f"{path} imports {module}"
            )


def test_only_composition_wires_infrastructure() -> None:
    for layer in ("domain", "application"):
        for path, modules in _layer(layer):
            assert not any(m.startswith(f"{PACKAGE}.infrastructure") for m in modules), path
    composition = _modules(ast.parse((ROOT / "composition.py").read_text()))
    assert any(module.startswith(f"{PACKAGE}.infrastructure") for module in composition)


def test_only_infrastructure_runs_processes() -> None:
    layers = [*_layer("domain"), *_layer("application")]
    layers.append(
        (ROOT / "composition.py", _modules(ast.parse((ROOT / "composition.py").read_text())))
    )
    for path, modules in layers:
        assert not {module.split(".")[0] for module in modules} & INFRA_ONLY_STDLIB, path


def test_the_review_use_case_is_covered_by_the_layer_checks() -> None:
    """As verificações acima varrem as pastas inteiras; isto garante que a revisão está nelas."""
    scanned = {path.relative_to(ROOT).as_posix() for layer in LAYERS for path, _ in _layer(layer)}
    for expected in (
        "domain/review/checks.py",
        "domain/review/strategies.py",
        "domain/review/tools.py",
        "infrastructure/repository/local.py",
        "infrastructure/repository/git.py",
        "application/review.py",
        "application/review_output.py",
    ):
        assert expected in scanned, expected
    review_domain = {m for path, ms in _layer("domain") if "review" in path.parts for m in ms}
    assert not any(module.startswith(f"{PACKAGE}.infrastructure") for module in review_domain)


LAYERS = ("domain", "application", "infrastructure")


def _layer(name: str) -> list[tuple[Path, set[str]]]:
    return [(path, _modules(ast.parse(path.read_text()))) for path in (ROOT / name).rglob("*.py")]


def _modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules
