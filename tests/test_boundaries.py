import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "agent_sample"

FRAMEWORKS = {
    "a2a",
    "typer",
    "langgraph",
    "langchain",
    "langchain_core",
    "deepagents",
    "laya",
    "httpx",
}
BANNED = {
    "domain": FRAMEWORKS,
    "application": FRAMEWORKS - {"a2a", "typer"},
}


def test_layers_do_not_import_foreign_frameworks() -> None:
    for layer, banned in BANNED.items():
        for path in (ROOT / layer).rglob("*.py"):
            tree = ast.parse(path.read_text())
            imported = _imports(tree)
            assert not (imported & banned), f"{path} imports {imported & banned}"


def test_infra_does_not_import_application() -> None:
    for path in (ROOT / "infrastructure").rglob("*.py"):
        tree = ast.parse(path.read_text())
        modules = _modules(tree)
        assert not any(module.startswith("agent_sample.application") for module in modules)


def _imports(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def _modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules
