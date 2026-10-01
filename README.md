# agent-sample: revisor de código

Revisa uma mudança de código (diff, duas referências git ou pull request) com um **workflow
determinístico** de ponta a ponta. A parte agêntica (Deep Agents) é **uma etapa dentro dele**, com
entrada, saída, limites e falha bem definidos. Exposto por CLI (Typer) e A2A.

```bash
uv sync
uv run reviewer review --diff-file examples/diffs/api_key.diff        # funciona sem credencial
uv run reviewer review --repo . --base main --head HEAD --format json
uv run reviewer review --pr https://github.com/dono/repo/pull/42        # GITHUB_TOKEN no ambiente
uv run reviewer review --pr dono/repo#42 --post                         # publica no PR
uv run reviewer-a2a                                                     # servidor A2A em 127.0.0.1:9999
```

## A revisão

- **Decisão** (`policy.decide`): qualquer achado `critical` ou `major` → `request_changes`; só
  `minor`/`nit` → `comment`; nenhum → `approve`.
- **Achados**: arquivo e linha (ou intervalo) no código novo, severidade
  (`critical|major|minor|nit`), categoria (`correctness|security|performance|maintainability|tests|style`),
  descrição, sugestão, origem (`check:<id>` ou `agent:<plugin:revisor>` com a skill) e evidência
  (trecho do diff; segredos encontrados saem mascarados).
- **Não revisados**: binários, gerados (lockfiles, `*.min.*`, `_pb2.py`, marcador "generated"),
  acima do limite de linhas, removidos — sempre com o motivo.
- **Caminho**: as 9 etapas com natureza e resultado, revisores acionados, plugins usados
  (`nome@versão source=… sha256=…`), skills carregadas (`plugin:skill@versão`), chamadas de
  ferramenta, achados descartados com o motivo, falhas e degradações.
- Não há campo de confiança: nem regras nem agentes inventam probabilidade.

Formatos (`--format`): `text` (padrão), `json`, `pr-comments`. Códigos de saída: `0` para
`approve`/`comment`, **`1` para `request_changes`** (uso em CI), **`2` para erro**. Erros saem como
uma linha curta em stderr, sem traceback.

## Workflow

| # | Etapa | Natureza | O que faz |
|---|---|---|---|
| 1 | `obtain` | determinística | Lê a mudança: texto, arquivo, `git diff base...head` ou PR (diff + contexto via REST). |
| 2 | `normalize` | determinística | Separa arquivos e trechos, detecta linguagem, marca não revisados. |
| 3 | `checks` | determinística | Segredos, resquícios de depuração, fonte sem teste, TODO/FIXME. |
| 4 | `plan` | determinística | Decide se o agente roda, em quantas partes e com quais revisores. |
| 5 | `agentic_review` | **agêntica** | Revisor principal + revisores de plugin propõem achados. |
| 6 | `validate` | determinística | Aceita ou descarta cada achado proposto, registrando o motivo. |
| 7 | `consolidate` | determinística | Junta, remove duplicados (fica a maior severidade), preserva as checagens. |
| 8 | `decide` | determinística | Aplica a política de decisão e monta o resumo. |
| 9 | `publish` | determinística | Renderiza no formato pedido; com `--post`, publica no PR. |

Modos (`--mode`): `workflow` (sem a etapa 5; mesma mudança, mesma saída byte a byte), `hybrid`
(padrão) e `agent` (sem a etapa 3; 6–8 continuam valendo — o agente nunca decide sozinho).

**Como a fronteira é garantida**

- O domínio define as etapas (`domain/workflow.py: STEPS`); o motor (`SequentialEngine`) só as
  executa e reporta o progresso. Só `agentic_review` tem natureza `agentic` (há teste).
- A etapa 5 vê o agente pela porta `AgentReviewer.review(AgentTask, ToolCatalog, Limits) ->
  AgentOutcome`. Recebe partes normalizadas, achados das checagens, plano e ferramentas; devolve
  **propostas** (`ProposedFinding`), que só viram `Finding` depois da validação da etapa 6.
- Qualquer exceção da etapa 5 (falha, tempo, rodadas) vira registro no caminho, e a revisão sai com
  os achados determinísticos. Sem credencial, `hybrid` registra a degradação; `agent` falha com
  mensagem clara.
- A consolidação coloca as checagens primeiro e só troca um duplicado por outro **mais grave**:
  o agente não remove nem rebaixa um `critical` das checagens.
- Regra de acionamento (etapa 4): não roda em `workflow`, sem arquivos revisáveis, em mudança só de
  documentação, ou sem modelo. Mudanças grandes viram partes por arquivo (`max_part_chars`).
- Escrita externa só na etapa 9, só com `--post` e só para fonte PR. As ferramentas do agente são
  somente leitura.

## Etapa agêntica com Deep Agents

`infrastructure/agents/deepagents.py`:

- revisor principal com o prompt da skill `lead-reviewer`, o índice de skills e a lista de
  revisores; delega pela ferramenta `task` aos revisores de plugin, que viram `subagents=`
  nativos com as ferramentas que declaram;
- `CatalogGuard` (middleware) esconde e recusa tudo que não for do catálogo do projeto,
  planejamento (`write_todos`) ou delegação (`task`): as ferramentas de arquivo e `execute` do
  framework nunca chegam ao modelo, e o subagente genérico padrão é substituído por um restrito;
- limites (`Limits`, configuráveis): rodadas de ferramenta (chamadas ao modelo), tempo total
  (`asyncio.wait_for`), tamanho de contexto (entrada truncada com aviso), número de delegações e
  tamanho da saída de ferramenta.

### Ferramentas (todas somente leitura)

`read_repo_file`, `search_code`, `list_repo_files`, `blame`, `load_skill`, `pr_context`. O
contrato (nome, descrição, parâmetros, o que acessa) está em `domain/tools.py`; a execução, em
`infrastructure/repository/`. Com duas referências git, a leitura é da revisão revisada via
`git show/grep/ls-tree/blame` — não há caminho de disco envolvido. Com diff em texto e `--repo`, o
leitor de diretório é confinado à raiz (bloqueia `..`, absolutos e symlinks para fora). Caminhos
são validados também no domínio. Saída acima do limite é truncada com aviso. Ferramentas de
repositório só são oferecidas quando há repositório; `pr_context`, quando a fonte é PR.

## Skills e plugins

Um plugin segue o formato do ecossistema de agentes e **não contém código executável**:

```
meu-plugin/
  .claude-plugin/plugin.json     {"name", "version": "1.2.0", "description", "author",
                                  "reviewer": {"requires": ">=1.0.0,<2.0.0"}}
  skills/<skill>/SKILL.md        frontmatter name + description; corpo = instruções
  agents/<revisor>.md            frontmatter name, description, tools, skills, languages, focus;
                                 corpo = instruções do revisor
```

- Suportado: manifesto (nome, versão semântica, descrição, autor, compatibilidade), skills no
  formato Agent Skills (arquivos de apoio são texto), revisores em `agents/`. Nomes de ferramenta
  do ecossistema `Read`, `Grep`, `Glob`, `LS` são mapeados para o catálogo; **ferramenta
  desconhecida (ex.: `Bash`) invalida o plugin**, assim como skill inexistente.
- Ignorado **com aviso** (`plugins show`/`validate`): `commands/`, `hooks/`, `scripts/`,
  `.mcp.json`, chaves `mcpServers`/`hooks`/`commands`, e `model`/`color` no frontmatter de revisores.
- `languages`/`focus` de um revisor decidem, na etapa 4, quando ele é oferecido; sem filtros, é
  sempre oferecido. O agente vê só o índice das skills e carrega o corpo com `load_skill`.
- O projeto traz seus critérios como o plugin embutido `src/agent_sample/plugins/code-review/1.0.0`,
  carregado pelo mesmo mecanismo dos externos.

### Fontes, precedência e lock

Fontes vêm de configuração TOML, não de código. Precedência: **embutido → usuário**
(`$XDG_CONFIG_HOME/agent-sample/reviewer.toml`) **→ projeto** (`./reviewer.toml` ou
`REVIEWER_CONFIG`). Exemplo completo em `examples/reviewer.toml`.

```toml
[[sources]]
name = "examples"
kind = "dir"                 # diretório local (caminho relativo ao arquivo de configuração)
path = "plugins"

[[sources]]
name = "company"
kind = "package"             # pacote Python instalado, entry point `agent_sample.review_plugins`
entry_point = "company-review"

[[sources]]
name = "community"
kind = "git"                 # repositório git fixado em commit ou tag (branch é recusado)
url = "https://github.com/example/review-plugins.git"
ref = "v1.2.0"
subdir = "plugins"

[plugins]
disabled = ["django-review"]

[limits]
max_tool_rounds = 8
timeout_seconds = 120

[pull_requests]
allowed_hosts = ["api.github.com"]
```

- **Lock**: `reviewer plugins lock` resolve as fontes e grava `reviewer.lock.json` ao lado da
  configuração: tipo, local, ref, versão resolvida (commit do git, versão do pacote) e o sha256 de
  cada `plugin@versão`. Na inicialização tudo é resolvido e comparado: fonte ausente do lock,
  conteúdo alterado ou tag movida **falham a inicialização** com mensagem clara. O embutido tem
  seu lock em `src/agent_sample/plugins/reviewer.lock.json` (`plugins lock --builtin`).
- **Imutabilidade e versões**: versão publicada = conteúdo travado pelo hash. Nova versão é um novo
  diretório (`<plugin>/<versão>/`). Versões coexistem; o padrão é a maior; `--plugin nome@versão`
  escolhe, e `reviewer compare --plugin a@1.0.0 --plugin a@1.1.0 --diff-file x.diff` compara lado
  a lado na mesma mudança.
- **Conflitos**: o mesmo nome de plugin em mais de uma fonte fica com a de maior precedência, e o
  conflito aparece em `plugins list`. Skills ou revisores com o mesmo nome em plugins diferentes
  resolvem pelo plugin de maior precedência e aparecem em `plugins list`/`skills list`.
- **Validação na inicialização**: manifesto, frontmatter, nomes, versões, referências a skills e a
  ferramentas, compatibilidade e lock. Nenhum erro de conteúdo aparece no meio de uma revisão.
- **Rastreabilidade**: a versão de uma skill é a versão do plugin que a contém (o hash do plugin a
  cobre). O caminho registra `plugin@versão` com fonte e hash, e cada skill carregada como
  `plugin:skill@versão`.
- Por requisição: `--plugin` escolhe plugins (o dono de `lead-reviewer` entra se nenhum escolhido o
  trouxer) e `--skill` restringe as skills oferecidas.

## Cliente REST e pull requests

`infrastructure/rest/client.py` (httpx): hosts permitidos por configuração, token de
`GITHUB_TOKEN` (nunca em log, erro, caminho ou saída), tempo limite, até 2 novas tentativas só em
429/502/503/504 e erros de conexão, e erros traduzidos (401/403/404). `rest/github.py` usa o
cliente em dois papéis: **fonte/destino determinísticos** (diff, descrição, issues ligadas por
"Fixes #n", status de CI e comentários na etapa 1; publicação como review com comentários por
linha na etapa 9) e, indiretamente, **contexto do agente** (`pr_context`). O domínio só conhece
`PullRequestHost` (obter mudança, obter contexto, publicar).

## A2A

Mensagem com o diff no texto, ou `pull_request`/`repository`/`base`/`head` em `metadata`, junto com
`mode`, `focus`, `language`, `plugins`, `skills`, `format` e `post`. O agent card anuncia a skill
`code_review` e um item por revisor dos plugins habilitados. Cada etapa gera uma atualização de
status `WORKING`; o resultado é um artefato com a revisão em JSON (`application/json`) e em texto.
Falhas marcam a tarefa como `TASK_STATE_FAILED`, sem deixar a exceção escapar.

## Variáveis de ambiente

- `MODEL_API_KEY`, `MODEL_BASE_URL`, `MODEL_NAME`: gateway OpenAI-compatible da etapa agêntica.
  Sem `MODEL_API_KEY`, o modo padrão entrega a revisão determinística e registra a degradação.
- `GITHUB_TOKEN`, `GITHUB_API_URL`: provedor de pull requests.
- `REVIEW_MODE`, `REVIEW_FORMAT`: padrões da CLI e do servidor A2A.
- `REVIEWER_CONFIG`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`: configuração e cache de fontes git.

## Camadas

```
application/     CLI e A2A: traduzem entrada/saída e chamam ReviewService. Sem regra de negócio.
domain/          O que fazer: modelo, diff, checagens, plano, políticas, ferramentas, portas, workflow.
infrastructure/  Como executar: motor, Deep Agents, modelo, git, REST, plugins, formatos de saída.
plugins/         Plugin embutido (conteúdo, não código) e seu lock.
composition.py   Único ponto que conhece as implementações concretas.
```

`tests/test_boundaries.py` verifica: domínio só com biblioteca padrão, sem `os`, `pathlib`,
`subprocess`, `asyncio`, `time`, `datetime`, `tomllib`, `importlib`… e sem mencionar frameworks,
URLs ou formato de conteúdo (`SKILL.md`, `plugin.json`, manifesto, frontmatter); sem protocolo de
chat no domínio; application só com domínio e protocolos de entrada/saída; infra sem application;
só a composição liga a infra; só o adaptador de agente conhece o framework; plugins sem código.

## Como estender

- **Checagem determinística**: escreva `ChangeSet -> tuple[Finding, ...]` em `domain/checks.py` e
  registre um `Check` em `CHECKS`. Nenhuma outra etapa muda.
- **Skill ou revisor especializado**: crie `skills/<nome>/SKILL.md` ou `agents/<nome>.md` numa
  **nova versão** do plugin (`<plugin>/<nova-versão>/`) e rode `reviewer plugins lock`. Sem código.
- **Plugin externo**: declare a fonte (`dir`, `package` ou `git`) em `reviewer.toml` e rode
  `reviewer plugins lock`. Sem código (há teste com `examples/plugins/django-review`).
- **Ferramenta de leitura**: adicione um `Tool(spec, run, needs)` em `TOOLS` (`domain/tools.py`);
  se precisar de I/O novo, estenda `RepositoryReader` e suas implementações. Vale para todo revisor
  que a referenciar em `tools:`.
- **Provedor REST de PR**: implemente `PullRequestHost` (ex.: `rest/gitlab.py` sobre `RestClient`)
  e registre em `PROVIDERS` (`composition.py`).
- **Formato de saída**: implemente `Renderer` (`name`, `render(review)`) em
  `infrastructure/output/` e registre em `FORMATS` (`composition.py`).
- **Framework da etapa agêntica**: implemente `AgentReviewer` (`unavailable()`, `review(task,
  tools, limits)`) em `infrastructure/agents/` e registre em `AGENTS` (`composition.py`; escolha por
  `REVIEW_AGENT`). Domínio, skills e plugins não mudam.

## Decisões sobre os pontos a validar

- **Carregamento de skills e subagentes**: o carregador nativo de skills do Deep Agents lê caminhos
  de um backend com "último vence" e não tem lock, precedência explícita, validação na
  inicialização nem rastreio de qual versão foi lida. Por isso a infra resolve as fontes e entrega
  ao framework só conteúdo validado: skills pelo `load_skill` do catálogo (registrado no caminho) e
  revisores pelo `subagents=` nativo (a delegação do framework é usada como está).
- **Ferramentas REST**: o contexto do PR é obtido de forma determinística na etapa 1 e servido ao
  agente por `pr_context`, sem rede na etapa agêntica. Critério: previsível (mesmo contexto para
  todos os revisores), custo fixo (um conjunto de chamadas por revisão, não por rodada) e
  rastreável (a fonte aparece na etapa 1). Publicar nunca é ferramenta do agente.
- **MCP**: não implementado. Caberia como adaptador de catálogo: uma `Tool` cujo contrato é
  declarado no domínio e cuja execução chama uma ferramenta específica de um servidor MCP em lista
  de permitidos, preservando somente leitura e catálogo controlado pelo projeto.
- **Segunda implementação**: nenhuma. Um motor (`sequential`) e um framework (Deep Agents). O
  motor LangGraph e o agente LangGraph do classificador foram removidos por não trazerem ganho aqui.

## Limitações conhecidas

- Revisão de PR sem `--repo` não tem ferramentas de leitura do repositório (só `load_skill` e
  `pr_context`); a leitura remota por REST não foi implementada.
- Fonte `package` localiza o diretório por `importlib.util.find_spec`, o que importa os pacotes
  pais do entry point (não o próprio).
- A checagem de segredos é por padrão textual: tem falsos negativos (formatos não listados) e pode
  ter falsos positivos em fixtures.
- "Rodadas de ferramenta" contam chamadas ao modelo somadas entre líder e subagentes; ao estourar,
  a parte inteira falha e os achados dela são perdidos (os determinísticos permanecem).
- Detecção de linguagem por extensão; `--language` ajuda na escolha de revisores, não reclassifica
  arquivos.
- Só GitHub como provedor; publicação usa a API de reviews e pode ser recusada se uma linha
  comentada não estiver no diff do PR.
- A busca em worktree cobre arquivos rastreados pelo git quando a raiz é um repositório
  (`git grep`); arquivos não rastreados só aparecem fora de repos git.

## Consolidação

Esta versão consolida 6 implementações paralelas da mesma especificação
(`docs/CODE_REVIEWER.md`), avaliadas por aderência (17–18 itens), critérios de aceite (1–10) e
qualidade (simplicidade, clareza do domínio, testabilidade, elegância da composição):

| Worktree | Aderência | Aceite | Testes | Veredito |
|---|---|---|---|---|
| `leviathan` | 17/17 | 10/10 | 116 | **base** da consolidação |
| `bannerfish` | 17/18 | 9.5/10 | 74 | probe de agente + contexto degradável |
| `razorfish` | 17/18 | 10/10 | 86 | publisher via protocolo + LEGACY_TOKENS |
| `acornworm` | 17/18 | 9.5/10 | 34 | rejeição de conteúdo executável em plugins |
| `triggerfish` | parcial (~80%) | 6.5/10 | 45 | incompleta, não commitada — nada aproveitado |
| `dugong` | 0/18 | 0/10 | — | fragmento do classificador antigo — descartada |

O que veio de cada uma, além da base:

- **bannerfish**: `--mode agent` sem modelo falha claro mesmo quando a etapa agêntica seria pulada
  (ex.: mudança só de docs); contexto parcial do PR degrada em avisos (`notices`) no caminho em
  vez de falhar a revisão.
- **razorfish**: `PullRequestPublisher` recebe um provedor (`_PullRequestProvider`) em vez do
  `GitHubProvider` concreto — adicionar outro provedor (ex.: GitLab) é implementar o protocolo e
  registrar na composição; teste de varredura `LEGACY_TOKENS` (classificador e motores antigos
  fora de todo o `src`).
- **acornworm**: `digest()` rejeita conteúdo executável (extensão `.py/.sh/.js/.exe` ou bit de
  permissão) e symlinks que escapam do root em fontes `dir`/`git` — o plugin continua sendo
  conteúdo, nunca código (com teste).
- **Fixes próprios**: `RestClient` reutiliza um `httpx.AsyncClient` (pool de conexões);
  `WorktreeReader.search` usa `git grep` em raízes git com fallback para varredura; padrões de
  debug JS/TS sem duplicação; erro específico para `base` sem `head` no A2A; `PullRequestContext`
  com campo `notices`.

## Verificação

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```
