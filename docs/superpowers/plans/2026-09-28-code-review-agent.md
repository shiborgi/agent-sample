# Agente de code review — plano de implementação

> **Para quem executa:** siga as tarefas em ordem; cada uma termina com testes verdes
> (`uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`). O spec pede **um único
> commit** no fim (critério 8), então não há commits intermediários.

**Objetivo:** adicionar um segundo caso de uso, a revisão de um diff unificado com decisão
`approve | comment | request_changes`, reaproveitando a arquitetura híbrida do classificador.

**Arquitetura:** o domínio ganha `domain/review/` (diff, checagens, workflow, validação, política de
decisão, ferramentas e estratégias). O que era do classificador e serve aos dois vira genérico:
erros, `Step`, `WorkflowStep[S]`, `Agent[T]`, `Toolbox`, `AgentTask` e seleção de skills. A infra
ganha leitura confinada do repositório e `git diff`; os mesmos motores e agentes executam os dois
casos. A composição continua sendo o único ponto que liga tudo.

**Tecnologias:** Python 3.12 (genéricos PEP 695), Typer, a2a-sdk, LangGraph, DeepAgents, pytest, ruff.

**Spec:** `docs/CODE_REVIEW_AGENT.md` (regras de camada em `docs/PLANNING.md`).

## Restrições globais

- Mínimo necessário; sem abstração sem uso, código morto ou erro engolido.
- O classificador continua funcionando; testes existentes só mudam onde uma assinatura foi generalizada.
- Nenhum teste acessa rede ou modelo real.
- `domain` só usa biblioteca padrão, sem `os`, `pathlib`, `subprocess`; não conhece protocolo de LLM.
- `application` só traduz; `infrastructure` não importa `application`/`composition`.
- Tudo em um único commit no branch `shiborgi/charybdis`.

## Review Focus

1. **Diff colado sem prefixos `a/` `b/` (ex.: `diff -u`)** → paths lidos do `+++`, sem erro.
2. **Diff com `\ No newline at end of file` e linhas de contexto vazias** → contagem de linhas certa.
3. **Segredo no diff aparece na saída** → a evidência mascara o valor (não vaza de novo no log de CI).
4. **Referência git começando com `-`** → erro claro, nunca vira opção do git.
5. **Cliente A2A tenta escolher o repositório do servidor** → `repo` não é opção por requisição.

Cada item tem teste na tarefa dona do código (Tarefas 2, 3, 6 e 8).

---

## Decisões de design

| Tema | Decisão | Por quê |
|---|---|---|
| Erros | `domain/errors.py`: `DomainError` (base), `ModelUnavailable`, `UnknownOption`, `ContentError`, `AgentFailed`, `AgentAttemptFailed`. `SubjectError(DomainError)` fica no classificador. | CLI/A2A tratam um único tipo base para os dois casos. |
| Caminho | `Step` vai para `domain/trace.py`; ganha kinds `validation`, `decision` e outcomes `completed`, `discarded`, `skipped`. | O caminho da revisão usa o mesmo contrato. |
| Workflow | `WorkflowStep[S]` genérico; `WorkflowEngine.run[S]`. Os motores não mudam de comportamento. | Os dois motores executam o workflow de revisão sem código novo. |
| Agente | Porta `Agent[T]`; `LangGraphAgent`/`DeepAgentsAgent` recebem um `AnswerReader[T]` (`parse_answer` ou `parse_review`). Limite de rodadas vem em `AgentRequest.max_tool_rounds`. | Um framework novo serve aos dois casos; leitura do JSON do modelo continua na infra. |
| Prompt | Placeholders globais em `render.py`: `subjects`, `severities`, `categories`, `decision_rule`, `skills`. | Validação na carga continua igual e o texto das listas vem do domínio. |
| Skills | `AgentTask(name, prompt, skills)`; skill pode se oferecer a uma tarefa com `tasks: <tarefa>` no frontmatter. Oferecidas = declaradas ∪ publicadas cuja última versão se marca. Tag de tarefa desconhecida falha na inicialização. | "Criar uma skill nova não exige mudar código" sem reeditar versões publicadas do classificador. |
| Confiança | A revisão não tem campo de confiança. | Regras não têm probabilidade e a "confiança" escrita por um LLM também não é. |
| Decisão | `critical`/`major` → `request_changes`; só `minor`/`nit` → `comment`; nenhum → `approve`. `Review.__post_init__` recusa decisão incoerente. | Regra explícita, num lugar só (`DECISION_RULE`). |
| Evidência | Sempre extraída do diff pelo domínio (regras e agente). Segredos são mascarados. | Não confia no texto do modelo; não repete o segredo na saída. |
| Duplicado | Mesmo arquivo, mesma categoria, linhas sobrepostas. Achado de regra nunca é alterado; o do agente é descartado e registrado. | O agente só acrescenta: não remove nem rebaixa. |
| Falha do agente (híbrido) | Primeira falha interrompe o agente; a revisão sai com as regras + passo `failed` + `fallback:rules-only`. | Literal ao spec; não martela um modelo indisponível. |
| Partes | Arquivos agrupados até `MAX_PART_CHARS`; arquivo maior que isso (ou com mais de `MAX_FILE_LINES`) é "não revisado". | Todo arquivo revisado cabe numa parte, sem cortar hunks. |
| Repositório | Porta `Repository` no domínio; `LocalRepository` na infra confina ao root (resolve symlinks). O domínio também recusa path absoluto/`..` antes de chamar a porta. | Defesa em dois níveis; testável sem disco no domínio. |
| A2A | Um servidor, duas skills (`classify_subject` padrão, `review_change`), escolhidas por `metadata.skill`. `repo` só vem do servidor (`REVIEW_REPO`). | Compatível com clientes atuais; cliente remoto não escolhe caminho do servidor. |
| CLI | Comando `subject review` (arquivo, `-`, `--text` ou `--base/--head`), `--format text|json`; `request_changes` sai com código **3**; erro sai com 1. | 2 é o código de erro de uso do Click; CI distingue os casos. |

## Estrutura de arquivos

```
src/agent_sample/domain/
  errors.py            NOVO  erros genéricos
  trace.py             NOVO  Step, StepKind, Outcome
  model.py             MUDA  classificador; importa Step/erros genéricos
  content.py           MUDA  AgentTask(name, ...), SkillVersion.tasks, AgentRequest.max_tool_rounds, REVIEW_TASK
  ports.py             MUDA  Agent[T], WorkflowEngine genérico
  tools.py             MUDA  RunContext, Tool[C], Toolbox(context, tools), LOAD_SKILL, TOOLS
  workflow.py          MUDA  WorkflowStep[S]
  strategies.py        MUDA  usa errors/trace/Toolbox novo
  review/
    model.py           Severity, Category, Decision, Finding, Unreviewed, Review, ProposedFinding, ReviewAnswer, erros de diff
    diff.py            DiffLine, Hunk, FileChange, parse_diff
    change.py          Change, prepare_change, linguagens, is_test/is_source, triage, split_parts
    checks.py          Check, CHECKS (secrets, debug-leftovers, missing-tests, pending-markers)
    workflow.py        ReviewState, REVIEW_WORKFLOW
    policy.py          limites, DECISION_RULE, decide, conclude
    validation.py      validate (achados do agente), merge (duplicados)
    ports.py           Repository, SearchHit, DiffSource, ChangeReviewer
    tools.py           ReviewContext, REVIEW_TOOLS
    strategies.py      WorkflowReviewer, AgentReviewer, HybridReviewer
    session.py         review_change
src/agent_sample/infrastructure/
  agents/answer.py     MUDA  AnswerReader, parse_review
  agents/langgraph.py  MUDA  genérico em T
  agents/deepagents.py MUDA  genérico em T; escrita no FS virtual negada
  content/files.py     MUDA  tasks no frontmatter, offered_skills, accepts, check_tasks
  content/render.py    MUDA  VARIABLES
  repository/local.py  NOVO  LocalRepository
  repository/git.py    NOVO  GitDiffSource
src/agent_sample/application/
  service.py           MUDA  Options base, error_message(DomainError)
  review.py            NOVO  ReviewOptions, ReviewService, compare_reviews
  review_output.py     NOVO  FORMATS (text, json), comparação
  a2a/options.py       MUDA  genérico (keys, lists)
  a2a/executor.py      MUDA  SkillExecutor + handlers
  a2a/card.py, server.py MUDA duas skills
  cli/app.py           MUDA  review, compare-review-prompts
src/agent_sample/composition.py MUDA  reviewers, repositório, git, bootstrap com dois serviços
src/agent_sample/content/prompts/review_change/v1.md                 NOVO
src/agent_sample/content/skills/{security-review,test-quality,python-practices}/v1.md NOVO
examples/review/*.diff  NOVO (gerados com git real)
tests/  test_review_diff.py, test_review_checks.py, test_review_agent.py, test_review_application.py NOVOS;
        fakes.py, test_boundaries.py, test_a2a.py, test_application.py, test_content.py, test_strategies.py MUDAM
```

---

### Tarefa 1: Generalizar o núcleo compartilhado

**Arquivos:** `domain/errors.py`, `domain/trace.py`, `domain/model.py`, `domain/content.py`,
`domain/ports.py`, `domain/tools.py`, `domain/workflow.py`, `domain/strategies.py`,
`infrastructure/agents/*.py`, `infrastructure/content/render.py`, `application/service.py`,
`composition.py`, testes existentes.

**Produz:**
- `DomainError`, `AgentFailed(source, reason)`, `AgentAttemptFailed(step, cause)`.
- `Step(kind, name, outcome, detail, prompt=None, skills=())` em `domain/trace.py`.
- `class Agent[T](Protocol): name; async def run(request: AgentRequest, tools: ToolCatalog) -> T`.
- `AgentRequest(text, prompt, skills, max_tool_rounds=MAX_TOOL_ROUNDS)`.
- `Toolbox(context: C, tools: tuple[Tool[C], ...])`, `RunContext(skills)`, `LOAD_SKILL`, `TOOLS`.
- `LangGraphAgent(gateway, read: AnswerReader[T])`, idem DeepAgents; `AnswerReader = Callable[[str, str], T]`.
- `Options.merge(**changes) -> Self`.

- [ ] Mover/generalizar conforme a tabela de decisões; atualizar imports dos testes.
- [ ] `uv run pytest -q` → os 79 testes existentes passam sem mudar asserções.

### Tarefa 2: Diff unificado e preparação da mudança

**Arquivos:** `domain/review/{model,diff,change}.py`, `tests/test_review_diff.py`.

**Produz:** `parse_diff(text) -> tuple[FileChange, ...]`; `FileChange.added`, `.new_lines`,
`.evidence(start, end)`, `.added_count`, `.removed_count`; `prepare_change(text, focus, language) -> Change`;
`triage(files) -> (reviewable, unreviewed)`; `split_parts(files, budget)`.

Testes (escrever primeiro, ver falhar, implementar):
- diff do git com dois arquivos → paths, status, números de linha novos corretos;
- `diff -u` sem `a/`/`b/` e com timestamp após tab → path certo (Review Focus 1);
- `\ No newline at end of file` e linha de contexto vazia → contagem certa (Review Focus 2);
- arquivo novo, removido, renomeado; `Binary files ... differ` → `binary=True`;
- `""`/espaços → `EmptyDiff`; texto qualquer → `InvalidDiff`; hunk com cabeçalho inválido ou truncado → `InvalidDiff`;
- `focus` fora das categorias e `language` desconhecida → `UnknownOption`;
- linguagem deduzida pela extensão; a informada vale só para arquivo sem extensão;
- triage: binário e grande viram `Unreviewed` com motivo; `split_parts` respeita o orçamento.

### Tarefa 3: Checagens determinísticas, workflow e política

**Arquivos:** `domain/review/{checks,workflow,policy}.py`, `tests/test_review_checks.py`.

**Produz:** `Check(name, run)`, `CHECKS`, `REVIEW_WORKFLOW`, `ReviewState`, `decide(findings)`,
`conclude(change, findings, unreviewed, reviewed_by, trace, notes=()) -> Review`, `DECISION_RULE`.

Testes:
- chave AWS, token GitHub, chave privada, atribuição `api_key = "..."` → `critical/security`;
  placeholder (`"changeme"`, `"${X}"`) não dispara; evidência mascarada (Review Focus 3);
- `print(`/`breakpoint()`/`console.log`/bloco comentado de código → `minor/maintainability`;
- código-fonte sem teste → um achado `minor/tests`; com teste no diff → nenhum; README não conta;
- `TODO`/`FIXME` adicionados → `nit`; removidos não;
- decisão: critical/major → `request_changes`, minor/nit → `comment`, nenhum → `approve`;
  `Review` com decisão incoerente → `ValueError`;
- `sequential` e `langgraph` produzem o mesmo `ReviewState`; mesma revisão duas vezes é idêntica.

### Tarefa 4: Validação dos achados do agente e fusão

**Arquivos:** `domain/review/validation.py`, testes em `tests/test_review_agent.py`.

**Produz:** `validate(proposals, files, source) -> (tuple[Finding, ...], tuple[Step, ...])`,
`merge(rules, agent) -> (tuple[Finding, ...], tuple[Step, ...])`.

Testes: arquivo fora do diff, linha fora do código novo, `end < start`, sem descrição, severidade
ou categoria inválida → descartado com motivo no passo `validation`; aceito ganha evidência do diff;
duplicado do agente com severidade menor → sai uma vez, `critical` da regra intacto.

### Tarefa 5: Ferramentas, repositório e git

**Arquivos:** `domain/review/{ports,tools}.py`, `infrastructure/repository/{local,git}.py`,
testes em `tests/test_review_agent.py` e `tests/test_review_application.py`.

**Produz:** `Repository.read(path) -> str`, `Repository.search(text, limit) -> tuple[SearchHit, ...]`,
`DiffSource.between(base, head) -> str`, `REVIEW_TOOLS` (`read_repo_file`, `search_repo`,
`list_criteria`, `load_skill`), `LocalRepository(root)`, `GitDiffSource(root)`.

Testes: `../x`, `/etc/passwd` e symlink para fora → erro de acesso e a porta nem é chamada para
os dois primeiros; busca não atravessa symlink para fora; trecho numerado e truncado; sem
repositório → mensagem clara; `git diff` entre dois commits de um repo temporário; ref `-x` →
`DiffUnavailable` (Review Focus 4).

### Tarefa 6: Estratégias de revisão, conteúdo e agentes reais

**Arquivos:** `domain/review/{strategies,session}.py`, `infrastructure/agents/answer.py`,
`infrastructure/content/files.py`, `content/prompts/review_change/v1.md`, três skills,
`published.json`, `tests/fakes.py`, `tests/test_review_agent.py`, `tests/test_content.py`.

Testes (agente falso, sem rede): caminho registra `review_change@v1` e skills carregadas; falha do
agente no híbrido mantém regras e registra `failed` + `fallback`; agente sozinho falha com erro;
diff grande revisado em partes (uma chamada por parte, achados juntados); `parse_review` lê JSON
tolerante e recusa texto sem JSON; `LangGraphAgent` e `DeepAgentsAgent` com gateway roteirizado
carregam skill, leem arquivo e produzem achados; skill com `tasks: review_change` é oferecida sem
mudar código; tag de tarefa desconhecida falha na inicialização.

### Tarefa 7: Aplicação — serviço, CLI e saída

**Arquivos:** `application/{review,review_output}.py`, `application/cli/app.py`, `composition.py`,
`examples/review/*.diff`, `tests/test_review_application.py`, `tests/test_application.py`.

Testes: tabela do critério 3 pela CLI sem credencial; `--format json` estável e idêntico em duas
execuções no modo workflow; `request_changes` → código 3; erro → 1 e uma linha em stderr, sem
traceback; `--base/--head` num repo temporário; nenhuma ou duas fontes de diff → erro claro;
`compare-review-prompts` com gateway roteirizado.

### Tarefa 8: A2A, fronteiras e README

**Arquivos:** `application/a2a/*.py`, `tests/test_a2a.py`, `tests/test_boundaries.py`, `README.md`.

Testes: A2A revisão com sucesso (artefato JSON, decisão), falha (diff vazio → `TASK_STATE_FAILED`),
skill desconhecida → falha; `metadata.repo` é ignorado (Review Focus 5); classificador A2A intacto;
fronteiras: `subprocess` só na infra, domínio sem `posixpath`/`subprocess`, e a varredura inclui
`domain/review`, `infrastructure/repository` e `application/review.py`.

README: forma de revisar, regra de decisão, validação, ferramentas, exemplos, variáveis de
ambiente e os cinco pontos de extensão do spec.

### Fechamento

- [ ] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- [ ] Rodar a CLI em cada exemplo sem `MODEL_API_KEY` e conferir a tabela.
- [ ] Um único commit.
