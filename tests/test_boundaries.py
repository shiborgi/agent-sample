import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "agent_sample"
PACKAGE = "agent_sample"

# domain: só biblioteca padrão, e nada que diga onde o conteúdo mora.
DOMAIN_BANNED_STDLIB = {"os", "pathlib", "importlib", "io", "shutil", "glob"}
# application: só os protocolos de entrada e saída.
APPLICATION_THIRD_PARTY = {"typer", "a2a", "starlette", "uvicorn"}


def test_domain_only_uses_stdlib_and_itself() -> None:
    for path, modules in _layer("domain"):
        for module in modules:
            top = module.split(".")[0]
            if top == PACKAGE:
                assert module.startswith(f"{PACKAGE}.domain"), f"{path} imports {module}"
            else:
                assert top in sys.stdlib_module_names, f"{path} imports {module}"
                assert top not in DOMAIN_BANNED_STDLIB, f"{path} imports {module}"


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
