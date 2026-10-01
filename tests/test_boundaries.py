"""Verificação automática das dependências entre camadas."""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "agent_sample"
PACKAGE = "agent_sample"

# domain: só biblioteca padrão, sem I/O, rede, processo, relógio nem formato de conteúdo.
DOMAIN_BANNED_STDLIB = {
    "os",
    "pathlib",
    "io",
    "shutil",
    "glob",
    "tempfile",
    "subprocess",
    "socket",
    "ssl",
    "urllib",
    "http",
    "time",
    "datetime",
    "asyncio",
    "random",
    "importlib",
    "tomllib",
    "sqlite3",
}
# nomes de frameworks, protocolos e formatos que o domínio não pode conhecer.
DOMAIN_UNKNOWN = re.compile(
    r"SKILL\.md|plugin\.json|\.claude-plugin|deepagents|langgraph|langchain|httpx|typer|"
    r"starlette|uvicorn|\ba2a\b|frontmatter|manifest|https?://|reviewer\.lock|reviewer\.toml",
    re.IGNORECASE,
)
# application: só os protocolos de entrada e saída.
APPLICATION_THIRD_PARTY = {"typer", "a2a", "starlette", "uvicorn"}
APPLICATION_BANNED_STDLIB = {"subprocess", "socket", "urllib", "http", "tomllib", "importlib"}
# protocolo de chat com o modelo: só a infra conhece.
LLM_PROTOCOL = {"ChatMessage", "Completion", "ModelGateway", "ToolCall", "GatewayChatModel"}
# motores, agentes e o classificador removidos: fora de todo o src.
LEGACY_TOKENS = re.compile(
    r"SubjectClassifier|classify_subject|subject-boundaries|out-of-scope|"
    r"WorkflowStrategy|AgentStrategy|PredictionStrategy|HybridStrategy|"
    r"LangGraphAgent|LangGraphEngine|LayaPredictor",
    re.IGNORECASE,
)


def test_domain_only_uses_stdlib_and_itself() -> None:
    for path, modules in _layer("domain"):
        for module in modules:
            top = module.split(".")[0]
            if top == PACKAGE:
                assert module.startswith(f"{PACKAGE}.domain"), f"{path} imports {module}"
            else:
                assert top in sys.stdlib_module_names, f"{path} imports {module}"
                assert top not in DOMAIN_BANNED_STDLIB, f"{path} imports {module}"


def test_domain_does_not_know_frameworks_io_or_content_format() -> None:
    for path in (ROOT / "domain").rglob("*.py"):
        text = path.read_text()
        found = DOMAIN_UNKNOWN.search(text)
        assert found is None, f"{path} mentions {found.group(0) if found else ''}"
        calls = {
            node.func.id
            for node in ast.walk(ast.parse(text))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert not calls & {"open", "input", "print", "exec", "eval"}, f"{path} does I/O"


def test_domain_does_not_know_the_llm_protocol() -> None:
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
                assert top not in APPLICATION_BANNED_STDLIB, f"{path} imports {module}"


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


def test_only_the_agent_adapter_knows_the_agent_framework() -> None:
    for path, modules in _layer("infrastructure"):
        uses = {m for m in modules if m.split(".")[0] in {"deepagents", "langchain", "langgraph"}}
        if uses:
            assert path.parent.name in {"agents", "model"}, f"{path} imports {uses}"


def test_legacy_classifier_and_runtimes_are_gone() -> None:
    """Nenhum resto do classificador, do motor LangGraph ou da predição 'laya'."""
    for path in sorted(ROOT.rglob("*.py")):
        text = path.read_text()
        found = LEGACY_TOKENS.search(text)
        assert found is None, f"{path} mentions {found.group(0) if found else ''}"


def test_plugins_hold_no_executable_code() -> None:
    for path in (ROOT / "plugins").rglob("*"):
        assert path.suffix not in {".py", ".sh", ".js"}, f"{path} is code inside a plugin"


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
