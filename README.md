# agent-sample

Dois casos de uso sobre a mesma arquitetura híbrida (workflow determinístico, agente e híbrido),
pela CLI (Typer) ou pelo protocolo A2A:

- **classificador:** o assunto de uma mensagem em `billing`, `technical`, `sales` ou `other`;
- **revisor de código:** revisa um diff e decide `approve`, `comment` ou `request_changes`
  ([seção própria](#revisão-de-código)).

```bash
uv sync
uv run subject classify "Fui cobrado duas vezes"          # funciona sem credencial de modelo
uv run subject compare "Erro na fatura"                   # todas as implementações lado a lado
uv run subject review examples/review/api_key.diff        # revisão; sem credencial usa as regras
uv run subject-a2a                                        # servidor A2A em 127.0.0.1:9999
```

## Formas de classificar

| `--strategy` | O que faz | Confiança |
|---|---|---|
| `workflow` | Regras explícitas e reproduzíveis. Empate ou falta de evidência → `other`. | não informa |
| `agent` | Um modelo raciocina, decide quando usar ferramentas (`list_subjects`, `load_skill`) e dá o veredito. | não informa |
| `hybrid` (padrão) | Regras primeiro; só chama o agente se as regras não decidem. Se o agente falhar, devolve `other` e registra o fallback no caminho e no log. | não informa |
| `prediction` | Laya: predição de passo único. **Não é agente**: não raciocina nem usa ferramentas. | a do modelo |

Implementações:

- motores do workflow (`--engine`): `sequential` (laço Python) e `langgraph` (um nó por etapa).
  Os dois executam as mesmas etapas do domínio e dão o mesmo resultado (há teste de equivalência).
- agentes (`--agent`): `langgraph` (laço ReAct explícito) e `deepagents`. Usam o mesmo prompt, as
  mesmas skills e as mesmas ferramentas.
- predição: `laya` (`uv sync --extra laya`).

As regras casam palavras inteiras depois de remover acentos e maiúsculas: "capital" não vira
`technical` (não casa `api`) e "demorando" não vira `sales` (não casa `demo`).

Confiança só aparece quando existe: regras não inventam probabilidade e a "confiança" que um LLM
escreve no texto não é uma probabilidade, então agentes não a informam.

### Veredito

Todo veredito traz assunto, justificativa, quem decidiu (`decided_by`) e o caminho. Quando houve
agente, o passo mostra a versão do prompt e as skills que ele carregou:

```
$ uv run subject classify "Erro na fatura"
other	fallback	n/a	regras empatadas: billing (fatura); technical (erro); agente falhou, usando assunto seguro
  1. workflow:sequential undecided — regras empatadas: billing (fatura); technical (erro)
  2. agent:langgraph failed prompt=classify_subject@v2 skills=- — model unavailable: MODEL_API_KEY is not set
  3. fallback:safe-subject decided — assunto seguro após falha do agente
```

## Uso

```bash
uv run subject classify "A API retorna 500" --strategy workflow --engine langgraph
uv run subject classify "Erro na fatura" --strategy agent --agent deepagents \
    --prompt-version v1 --skill subject-boundaries@v1
uv run subject compare-prompts "Erro na fatura" --version v1 --version v2
uv run subject prompts list
uv run subject prompts show classify_subject --version v1
uv run subject skills list
uv run subject skills show out-of-scope
```

Erros aparecem como uma linha curta em stderr e código de saída 1, sem traceback.

Variáveis de ambiente:

- `MODEL_BASE_URL`, `MODEL_API_KEY`, `MODEL_NAME`: gateway OpenAI-compatible dos agentes. Sem
  `MODEL_API_KEY`, o uso padrão continua funcionando: as regras resolvem o que dá e o resto cai no
  fallback `other`. `--strategy agent` falha com mensagem clara.
- `STRATEGY`, `ENGINE`, `AGENT`, `PROMPT_VERSION`: padrões da CLI e do servidor A2A (substituem o
  antigo `CLASSIFIER`).
- `CONTENT_DIR`: diretório alternativo de prompts e skills.

### A2A

Cada requisição pode escolher a forma de classificar em `params.metadata`; o que faltar usa o padrão
do servidor. Falhas marcam a tarefa como `TASK_STATE_FAILED` com a mensagem de erro.

```json
{"jsonrpc": "2.0", "id": 1, "method": "SendMessage",
 "params": {"message": {"messageId": "m1", "role": "ROLE_USER", "parts": [{"text": "Erro na fatura"}]},
            "metadata": {"strategy": "agent", "agent": "deepagents", "prompt_version": "v1"}}}
```

## Revisão de código

`subject review` revisa uma mudança em diff unificado e devolve a decisão, um resumo, os achados,
os arquivos não revisados e o caminho percorrido.

```bash
uv run subject review mudanca.diff                       # arquivo ('-' lê da entrada padrão)
uv run subject review --text "$(git diff)"               # texto
uv run subject review --base main --head HEAD            # duas referências git de --repo (padrão: .)
uv run subject review mudanca.diff --strategy workflow --format json
uv run subject review mudanca.diff --strategy agent --agent deepagents \
    --prompt-version v1 --skill security-review@v1 --focus security --focus tests
uv run subject compare-review-prompts mudanca.diff --version v1
```

Código de saída: **0** para `approve` e `comment`, **3** para `request_changes` (para CI) e **1**
para erro (uma linha curta em stderr, sem traceback). O 2 fica com o Click, para erro de uso.

### Formas de revisar

| `--strategy` | O que faz |
|---|---|
| `workflow` | Checagens explícitas, sem modelo. Mesmo diff, mesma saída, byte a byte. |
| `agent` | O agente lê a mudança por partes, investiga com ferramentas e propõe achados. |
| `hybrid` (padrão) | Workflow primeiro; depois o agente, que recebe os achados das regras e só pode acrescentar. Se o agente falhar, a revisão sai com os achados das regras e o caminho registra a falha. |

Os motores (`--engine sequential|langgraph`) e os agentes (`--agent langgraph|deepagents`) são os
mesmos do classificador.

Checagens do workflow (`domain/review/checks.py`), só em linhas adicionadas:

| Checagem | Achado |
|---|---|
| `secrets` | chave AWS, token GitHub/Slack, `sk-...`, chave privada, `api_key = "..."` → `critical/security` |
| `debug-leftovers` | `print(`, `breakpoint()`, `pdb`, `console.log`, `debugger`, `binding.pry`; 3+ linhas de código comentado → `minor/maintainability` |
| `missing-tests` | código-fonte alterado sem nenhum arquivo de teste no diff → um achado `minor/tests` |
| `pending-markers` | `TODO`/`FIXME` adicionados → `nit/maintainability` |

Antes das checagens, a triagem separa **binários** e **arquivos grandes** (mais de 1000 linhas
alteradas ou mais de 30 mil caracteres de diff): eles não são revisados por ninguém e aparecem
em "não revisados" com o motivo.

### A revisão

- **Decisão** (`DECISION_RULE`, `domain/review/model.py`): qualquer achado `critical` ou `major` →
  `request_changes`; só `minor` ou `nit` → `comment`; nenhum achado → `approve`. `Review` recusa
  uma decisão que não siga a regra.
- **Achado:** arquivo e linha (ou intervalo) no código novo, severidade, categoria
  (`correctness`, `security`, `performance`, `maintainability`, `tests`, `style`), descrição,
  sugestão, origem (`rule` ou `agent`, com a fonte: `rule:secrets`, `agent:langgraph`) e evidência.
- **Evidência** vem sempre do diff, nunca do texto do agente. Segredos são mascarados
  (`"9f8e****"`) na evidência, na descrição e no resumo, para a saída do CI não repetir a credencial.
- **Confiança** não aparece: regras não têm probabilidade e a "confiança" que um LLM escreve também
  não é uma.
- **Caminho:** cada etapa do workflow, cada parte revisada pelo agente (com `prompt=` e as skills
  carregadas), cada achado descartado com o motivo e a decisão.

### O agente revisor

Ferramentas (`domain/review/tools.py`), todas somente leitura:

- `read_repo_file(path, start_line, end_line)`: até 200 linhas numeradas de um arquivo do repositório;
- `search_repo(text)`: busca literal, até 30 ocorrências;
- `list_criteria()`: severidades, categorias, regra de decisão e índice das skills;
- `load_skill(name)`: corpo de uma skill.

O domínio recusa caminhos absolutos, `~` e `..` antes de chamar o repositório; `LocalRepository`
resolve symlinks e recusa tudo o que sai da raiz. O DeepAgents traz ferramentas próprias sobre um
sistema de arquivos virtual em memória; a escrita nele é negada. Nenhuma ferramenta executa código.

Limites (`domain/review/policy.py`): 8 rodadas de ferramenta por parte, 8 mil caracteres por resposta
de ferramenta e partes de até 30 mil caracteres de diff. Um diff maior é revisado em partes (arquivos
inteiros por parte) e a revisão junta os achados. A primeira falha do agente interrompe as partes
restantes.

**Validação dos achados do agente** (`domain/review/validation.py`). Cada descarte vira um passo
`validation` no caminho, com o motivo:

- arquivo que não está nas partes revisadas;
- linha (início ou fim) que não aparece no código novo do diff (linha adicionada ou de contexto);
- intervalo inválido, sem descrição, severidade ou categoria fora da lista.

**Fusão no híbrido:** os achados das regras nunca mudam. Um achado do agente no mesmo arquivo, na
mesma categoria e com linhas sobrepostas a um já existente é duplicado: sai uma vez só e o descarte
fica registrado. Por isso o agente não remove nem rebaixa um `critical` das regras.

### Exemplos versionados

Em `examples/review/`, gerados com `git diff`. Sem `MODEL_API_KEY`, o padrão (`hybrid`) dá:

| Diff | Resultado |
|---|---|
| `api_key.diff` | `critical/security` (+ `minor/tests`); `request_changes`, código 3 |
| `debug_print.diff` | `minor/maintainability`; `comment` |
| `source_without_tests.diff` | `minor/tests`; `comment` |
| `clean_with_test.diff` | nenhum achado; `approve` |
| `binary_file.diff` | `assets/logo.png` em "não revisados", sem erro; `approve` |
| `empty.diff` | `error: diff is empty`, código 1 |

O caminho registra `agent:langgraph failed ... model unavailable` e `fallback:rules-only`.

### A2A

O servidor tem duas skills: `classify_subject` (padrão) e `review_change`. A skill vai em
`params.metadata.skill`; o texto da mensagem é o diff e o artefato é a revisão em JSON
(`application/json`, o mesmo formato de `--format json`). Opções por requisição: `strategy`,
`engine`, `agent`, `prompt_version`, `skills` e `focus` (lista ou texto separado por vírgula) e
`language`. O repositório lido pelas ferramentas **não** é opção de requisição: vem de
`REVIEW_REPO` no servidor (sem ele, as ferramentas avisam que não há repositório).

```json
{"jsonrpc": "2.0", "id": 1, "method": "SendMessage",
 "params": {"message": {"messageId": "m1", "role": "ROLE_USER", "parts": [{"text": "diff --git ..."}]},
            "metadata": {"skill": "review_change", "strategy": "workflow", "focus": ["security"]}}}
```

Variáveis de ambiente da revisão: `REVIEW_STRATEGY`, `REVIEW_ENGINE`, `REVIEW_AGENT`,
`REVIEW_PROMPT_VERSION`, `REVIEW_REPO`. Opções inválidas nelas falham na inicialização.

### Linguagem e foco

A linguagem sai da extensão; `--language` vale para arquivos sem extensão (ex.: `bin/tool`). Ela
escolhe os padrões de depuração e diz o que é código-fonte. `--focus` (categorias) chega ao agente;
as regras sempre rodam todas.

## Camadas

```
application/   CLI e A2A: traduzem entrada/saída e chamam ClassificationService ou ReviewService.
domain/        O que fazer: regras, etapas do workflow, estratégias, escalada e fallback,
               ferramentas do agente, contrato do veredito, capacidades pedidas (AgentTask).
  review/      Revisão: diff, checagens, workflow, política de decisão, validação dos achados,
               ferramentas, portas (Repository, DiffSource) e estratégias.
infrastructure/ Como executar: motores, agentes, gateway do modelo, Laya, conteúdo em arquivos,
               leitura confinada do repositório e git diff (repository/).
content/       Prompts e skills (conteúdo, não código).
composition.py Único ponto que conhece as implementações concretas.
```

Genérico e compartilhado pelos dois casos: erros (`domain/errors.py`), o caminho (`Step` em
`domain/trace.py`), `WorkflowStep[S]` e os motores, a porta `Agent[T]` e os dois agentes (que
recebem o leitor da resposta: `parse_answer` ou `parse_review`), `Toolbox`/`load_skill`,
`AgentTask`, a seleção de skills e os placeholders de prompt.

`tests/test_boundaries.py` verifica as dependências: o domínio só usa a biblioteca padrão (e nada
de `os`/`pathlib`/`subprocess`, porque não sabe onde o conteúdo mora nem lê disco ou git); a
application só conhece domínio e protocolos; a infra não conhece application; só a composição
importa a infra; só a infra executa processos. Um teste garante que os módulos da revisão estão
na varredura.

O domínio também não conhece o protocolo do modelo. A porta de agente é
`Agent[T].run(AgentRequest, ToolCatalog) -> T`: o domínio entrega a entrada da tarefa, a versão do
prompt, as skills e o limite de rodadas, e recebe a resposta da tarefa (`AgentAnswer` com assunto e
justificativa, ou `ReviewAnswer` com os achados propostos). Mensagens de chat e gateway
(`infrastructure/model/ports.py`), montagem do prompt de sistema
(`infrastructure/content/render.py`) e leitura do JSON do modelo
(`infrastructure/agents/answer.py`) ficam na infra.

## Prompts e skills

```
src/agent_sample/content/
  prompts/classify_subject/v1.md, v2.md       # templates com $subjects e $skills
  prompts/review_change/v1.md                 # $severities, $categories, $decision_rule, $skills
  skills/subject-boundaries/v1.md             # frontmatter "description:" + corpo
  skills/out-of-scope/v1.md
  skills/security-review/v1.md                # frontmatter com "tasks: review_change"
  skills/test-quality/v1.md
  skills/python-practices/v1.md
  published.json                              # sha256 de cada versão publicada
```

- O domínio declara o que cada tarefa pede (`CLASSIFY_TASK`: prompt `classify_subject` e as skills
  `subject-boundaries` e `out-of-scope`; `REVIEW_TASK`: prompt `review_change`), sem fixar
  versões. Uma skill também se oferece a uma tarefa com `tasks: <tarefa>` no frontmatter; a
  tarefa recebe as declaradas e as publicadas cuja versão padrão se marca. Tarefa desconhecida em
  `tasks:` falha na inicialização. Os dois agentes usam o mesmo conteúdo.
- Placeholders disponíveis em qualquer prompt: `$subjects`, `$severities`, `$categories`,
  `$decision_rule` e `$skills` (`infrastructure/content/render.py`).
- O prompt recebe só o índice das skills (nome + descrição). O corpo entra quando o agente chama
  `load_skill`, e cada skill carregada aparece no caminho do veredito como `nome@versão`.
- Versão publicada não muda: se o arquivo divergir do hash em `published.json`, a inicialização
  falha. Arquivos fora do manifesto são rascunhos: podem ser escolhidos explicitamente
  (`--prompt-version v3`), mas o padrão é sempre a maior versão publicada.
- Tudo é validado na inicialização (frontmatter, placeholders, nomes de versão, arquivos do
  manifesto, conteúdo exigido pela tarefa, padrões do ambiente), antes de qualquer classificação.

## Como estender

- **Nova versão de prompt:** crie `content/prompts/classify_subject/v3.md` (use `$subjects` e
  `$skills`), teste com `--prompt-version v3` e `compare-prompts`, e publique com
  `uv run subject content publish prompt classify_subject v3`. Ela vira o padrão.
- **Nova skill:** crie `content/skills/<nome>/v1.md` com `description:` no frontmatter, publique
  com `uv run subject content publish skill <nome> v1` e adicione o nome em `CLASSIFY_TASK`
  (`domain/content.py`). Nova versão de skill existente: só o arquivo + publish.
- **Nova ferramenta:** adicione um `Tool(spec, run)` em `TOOLS` (`domain/tools.py`). Os dois agentes
  a recebem automaticamente.
- **Novo motor de workflow:** implemente `WorkflowEngine.run(steps, state)` em
  `infrastructure/workflow/` e registre em `ENGINES` (`composition.py`).
- **Novo agente de outro framework:** implemente `Agent.run(request, tools) -> AgentAnswer` em
  `infrastructure/agents/`, montando o prompt com `render_prompt` e lendo a resposta com
  `parse_answer`, e registre em `AGENTS` (`composition.py`).
- **Nova estratégia:** crie a classe em `domain/strategies.py` (qualquer objeto com `name` e
  `classify(text) -> Verdict`) e registre o construtor em `STRATEGIES` (`composition.py`).

Na revisão de código:

- **Nova checagem determinística:** escreva `(change, files) -> tuple[Finding, ...]` em
  `domain/review/checks.py` (use `rule_finding`, que mascara segredos e tira a evidência do diff) e
  registre `Check("nome", função)` em `CHECKS`. O workflow ganha a etapa `nome`, os dois motores a
  executam e o caminho a mostra.
- **Nova skill de revisão (tema ou linguagem):** crie `content/skills/<nome>/v1.md` com
  `description:` e `tasks: review_change` no frontmatter e publique com
  `uv run subject content publish skill <nome> v1`. Nenhum código muda: o agente passa a vê-la no
  índice e a carrega com `load_skill`. Antes de publicar, dá para testar com `--skill <nome>@v1`.
- **Novo agente de outro framework:** implemente `run(request, tools) -> T` recebendo no construtor o
  gateway e um `AnswerReader[T]`; monte o prompt com `render_prompt`, respeite
  `request.max_tool_rounds` e devolva `read(texto_final, nome)`. Registre em `AGENTS`
  (`composition.py`): ele serve ao classificador e ao revisor.
- **Novo formato de saída (ex.: comentários de pull request):** escreva `Review -> str` em
  `application/review_output.py` e registre em `FORMATS`; `--format <nome>` passa a existir.
- **Nova ferramenta de leitura ao agente:** adicione um `Tool(spec, run)` em `REVIEW_TOOLS`
  (`domain/review/tools.py`); ela recebe o `ReviewContext` (skills e repositório). Se precisar de
  uma nova capacidade de leitura, amplie a porta `Repository` (`domain/review/ports.py`) e
  `LocalRepository` (`infrastructure/repository/local.py`), mantendo o confinamento à raiz.

## Limitações da revisão

- As checagens são heurísticas de texto: `missing-tests` aceita qualquer teste no diff, sem
  casar arquivo com teste; `print(` é tratado como depuração até em código de CLI; segredos só são
  reconhecidos pelos padrões listados.
- Um diff só com binários ou arquivos grandes sai `approve`, com a lista de "não revisados": a regra
  de decisão olha achados, não cobertura.
- O agente só aponta linhas visíveis no diff; um problema numa linha que ele leu com
  `read_repo_file`, fora dos hunks, é descartado.
- No híbrido, a primeira parte que falha descarta o agente inteiro, mesmo que partes anteriores
  tenham dado certo.
- Paths que o git escreve entre aspas (ex.: com caracteres não ASCII) não são decodificados.
- Com `--text` ou arquivo, as ferramentas leem `--repo` (padrão: diretório atual), que pode não ser
  o repositório de onde o diff veio.

## Verificação

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```
