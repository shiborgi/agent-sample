"""Etapa agêntica com Deep Agents: revisor principal que planeja, carrega skills e delega.

O domínio só vê `AgentReviewer.review(task, tools, limits) -> AgentOutcome`. Aqui ficam as
mensagens, o grafo, o middleware e a leitura da resposta do modelo.

- Skills: o índice vai no prompt e o corpo chega pela ferramenta `load_skill` do catálogo do
  projeto (não pelo carregador nativo), para valer o lock, a precedência e o rastreio.
- Revisores de plugin viram `subagents=` nativos, com as ferramentas que declaram.
- Ferramentas embutidas do framework (arquivos, `execute`) ficam escondidas e recusadas por
  `CatalogGuard`: só o catálogo do projeto, o planejamento e a delegação passam.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.errors import GraphRecursionError

from agent_sample.domain.capabilities import Reviewer
from agent_sample.domain.diff import FileChange
from agent_sample.domain.model import AgentLimitExceeded, ProposedFinding, ReviewError
from agent_sample.domain.plan import AgentTask
from agent_sample.domain.policy import Limits
from agent_sample.domain.ports import AgentOutcome, ToolCatalog, ToolSpec
from agent_sample.infrastructure.model.langchain_chat import GatewayChatModel
from agent_sample.infrastructure.model.ports import ModelGateway

FRAMEWORK_TOOLS = ("task", "write_todos")
LEAD = "lead"
GENERAL = "general-purpose"

OUTPUT_CONTRACT = """
Formato da resposta final (obrigatório): apenas um objeto JSON, sem texto fora dele:
{"findings": [{"file": "caminho/no/diff", "start_line": 10, "end_line": 12,
  "severity": "critical|major|minor|nit",
  "category": "correctness|security|performance|maintainability|tests|style",
  "description": "o problema", "suggestion": "como corrigir",
  "evidence": "trecho copiado do diff", "reviewer": "quem encontrou", "skill": "skill usada"}]}
Linhas são do código novo (coluna "new" do diff). Sem achados: {"findings": []}.
"""


class CatalogGuard(AgentMiddleware[Any, Any, Any]):
    """Só oferece e só executa ferramentas permitidas; conta rodadas e delegações."""

    def __init__(self, allowed: frozenset[str], limits: Limits, counters: dict[str, int]) -> None:
        self._allowed = allowed
        self._limits = limits
        self._counters = counters

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> Any:
        self._counters["model_calls"] += 1
        if self._counters["model_calls"] > self._limits.max_tool_rounds + 1:
            raise AgentLimitExceeded(f"{self._limits.max_tool_rounds} tool rounds")
        tools = [tool for tool in request.tools if _tool_name(tool) in self._allowed]
        return await handler(request.override(tools=tools))

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        call = request.tool_call
        name = call["name"]
        if name not in self._allowed:
            return _refusal(call, f"{name} is not available")
        if name == "task":
            if self._counters["subagents"] >= self._limits.max_subagents:
                return _refusal(call, f"subagent limit reached ({self._limits.max_subagents})")
            self._counters["subagents"] += 1
        return await handler(request)


def _refusal(call: dict[str, Any], message: str) -> ToolMessage:
    return ToolMessage(
        content=f"Error: {message}.",
        tool_call_id=call.get("id") or "",
        name=call["name"],
        status="error",
    )


def _tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        return str(tool.get("name") or (tool.get("function") or {}).get("name") or "")
    return str(getattr(tool, "name", ""))


class DeepAgentsReviewer:
    name = "deepagents"

    def __init__(self, gateway: ModelGateway, unavailable: str | None = None) -> None:
        self._gateway = gateway
        self._unavailable = unavailable

    def unavailable(self) -> str | None:
        return self._unavailable

    async def review(self, task: AgentTask, tools: ToolCatalog, limits: Limits) -> AgentOutcome:
        from deepagents import create_deep_agent

        counters = {"model_calls": 0, "subagents": 0}
        catalog = {spec.name: spec for spec in tools.specs()}
        lead_tools = [_tool(spec, tools) for spec in catalog.values()]
        allowed = frozenset(catalog) | frozenset(FRAMEWORK_TOOLS)
        model = GatewayChatModel(self._gateway)
        subagents = [
            _general(task, lead_tools, CatalogGuard(allowed, limits, counters)),
            *(
                _subagent(reviewer, tools, catalog, CatalogGuard(allowed, limits, counters))
                for reviewer in task.reviewers
            ),
        ]
        agent = create_deep_agent(
            model=model,
            tools=lead_tools,
            system_prompt=_system_prompt(task),
            middleware=[CatalogGuard(allowed, limits, counters)],
            subagents=subagents,
        )
        try:
            result = await asyncio.wait_for(
                agent.ainvoke(
                    {"messages": [{"role": "user", "content": _request(task, limits)}]},
                    config={"recursion_limit": (limits.max_tool_rounds + 2) * 4},
                ),
                timeout=limits.timeout_seconds,
            )
        except TimeoutError:
            raise AgentLimitExceeded(f"timeout of {limits.timeout_seconds:g}s") from None
        except GraphRecursionError:
            raise AgentLimitExceeded("graph recursion limit") from None
        messages = result.get("messages") or []
        if not messages:
            raise ReviewError("agent ended without an answer")
        invoked = _invoked(messages, task.reviewers)
        proposed = parse_findings(_text(messages[-1].content), task.reviewers)
        return AgentOutcome(proposed, (LEAD, *invoked))


def _tool(spec: ToolSpec, catalog: ToolCatalog) -> StructuredTool:
    async def call(**arguments: Any) -> str:
        return await catalog.call(spec.name, arguments)

    return StructuredTool.from_function(
        coroutine=call,
        name=spec.name,
        description=spec.description,
        args_schema=spec.parameters,
    )


def _general(task: AgentTask, tools: list[StructuredTool], guard: CatalogGuard) -> dict[str, Any]:
    """Substitui o subagente genérico padrão, que traria as ferramentas de arquivo do framework."""
    return {
        "name": GENERAL,
        "description": "Revisor genérico para investigar uma pergunta pontual sobre a mudança.",
        "system_prompt": f"{task.lead.body}\n{OUTPUT_CONTRACT}",
        "tools": tools,
        "middleware": [guard],
    }


def _subagent(
    reviewer: Reviewer,
    catalog: ToolCatalog,
    specs: dict[str, ToolSpec],
    guard: CatalogGuard,
) -> dict[str, Any]:
    tools = [_tool(specs[name], catalog) for name in reviewer.tools if name in specs]
    skills = ", ".join(f"{reviewer.plugin}:{skill}" for skill in reviewer.skills) or "-"
    return {
        "name": reviewer.name,
        "description": reviewer.description,
        "system_prompt": (
            f"{reviewer.instructions}\n\nSkills recomendadas (carregue com load_skill): {skills}\n"
            f'Use reviewer = "{reviewer.ref}".\n{OUTPUT_CONTRACT}'
        ),
        "tools": tools,
        "middleware": [guard],
    }


def _system_prompt(task: AgentTask) -> str:
    index = "\n".join(
        f"- {skill.plugin}:{skill.name}: {skill.description}" for skill in task.skills
    )
    reviewers = "\n".join(f"- {item.name}: {item.description}" for item in task.reviewers)
    return (
        f"{task.lead.body}\n\n"
        f"Skills disponíveis (carregue com load_skill):\n{index or '- (nenhuma)'}\n\n"
        f"Revisores especializados (delegue com a ferramenta task):\n{reviewers or '- (nenhum)'}\n"
        f"Ao juntar achados dos revisores, preserve o campo reviewer de cada um.\n"
        f"{OUTPUT_CONTRACT}"
    )


def _request(task: AgentTask, limits: Limits) -> str:
    sections = [f"Parte: {task.label}", f"Linguagens: {', '.join(task.languages) or '-'}"]
    if task.focus:
        sections.append(f"Foco pedido: {', '.join(task.focus)}")
    if task.context is not None:
        sections.append(f"Contexto do pull request:\n{task.context.render()}")
    if task.check_findings:
        known = "\n".join(
            f"- [{item.severity}/{item.category}] {item.location}: {item.description}"
            for item in task.check_findings
        )
        sections.append(f"Achados das checagens determinísticas (já registrados):\n{known}")
    sections.append(
        "Diff (new = linha no código novo):\n" + "\n".join(map(render_file, task.files))
    )
    text = "\n\n".join(sections)
    if len(text) > limits.max_context_chars:
        omitted = len(text) - limits.max_context_chars
        text = f"{text[: limits.max_context_chars]}\n[truncated: {omitted} characters omitted]"
    return text


def render_file(file: FileChange) -> str:
    lines = [f"### {file.path} ({file.status}, {file.language})", " new | diff"]
    for hunk in file.hunks:
        lines.append("  ... |")
        for line in hunk.lines:
            number = f"{line.new_line:>4}" if line.new_line is not None else "    "
            lines.append(f"{number} | {line.kind}{line.text}")
    return "\n".join(lines)


def _invoked(messages: list[Any], reviewers: tuple[Reviewer, ...]) -> tuple[str, ...]:
    refs = {reviewer.name: reviewer.ref for reviewer in reviewers}
    seen: list[str] = []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            if call.get("name") != "task":
                continue
            kind = str((call.get("args") or {}).get("subagent_type") or "")
            name = refs.get(kind, kind)
            if name and name not in seen:
                seen.append(name)
    return tuple(seen)


def parse_findings(text: str, reviewers: tuple[Reviewer, ...]) -> tuple[ProposedFinding, ...]:
    """Lê o JSON final. Campos estranhos passam adiante e a validação do domínio os descarta."""
    payload = _extract_json(text)
    items = payload.get("findings")
    if not isinstance(items, list):
        raise ReviewError("agent answer has no 'findings' list")
    known = {reviewer.name: reviewer.ref for reviewer in reviewers} | {
        reviewer.ref: reviewer.ref for reviewer in reviewers
    }
    proposed: list[ProposedFinding] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        start = _int(item.get("start_line"))
        reviewer = str(item.get("reviewer") or LEAD)
        proposed.append(
            ProposedFinding(
                file=str(item.get("file") or ""),
                start_line=start,
                end_line=_int(item.get("end_line")) or start,
                severity=str(item.get("severity") or ""),
                category=str(item.get("category") or ""),
                description=str(item.get("description") or ""),
                suggestion=str(item.get("suggestion") or ""),
                evidence=str(item.get("evidence") or ""),
                reviewer=known.get(reviewer, LEAD),
                skill=str(item["skill"]) if item.get("skill") else None,
            )
        )
    return tuple(proposed)


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start < 0 or end < start:
        raise ReviewError("agent answer is not JSON")
    try:
        payload = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ReviewError(f"agent answer is not valid JSON ({exc.msg})") from None
    if not isinstance(payload, dict):
        raise ReviewError("agent answer must be a JSON object")
    return payload


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block if isinstance(block, str) else str(block.get("text") or "")
            for block in content
            if isinstance(block, str) or (isinstance(block, dict) and block.get("type") == "text")
        )
    return str(content)
