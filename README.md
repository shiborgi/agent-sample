# agent-sample

Classifica o assunto de uma mensagem em `billing`, `technical`, `sales` ou `other`, pela CLI
(Typer) ou pelo protocolo A2A.

```bash
uv sync
uv run subject classify "Fui cobrado duas vezes"          # funciona sem credencial de modelo
uv run subject compare "Erro na fatura"                   # todas as implementações lado a lado
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

## Camadas

```
application/   CLI e A2A: traduzem entrada/saída e chamam ClassificationService (ponto único).
domain/        O que fazer: regras, etapas do workflow, estratégias, escalada e fallback,
               ferramentas do agente, contrato do veredito, capacidades pedidas (AgentTask).
infrastructure/ Como executar: motores, agentes, gateway do modelo, Laya, conteúdo em arquivos.
content/       Prompts e skills (conteúdo, não código).
composition.py Único ponto que conhece as implementações concretas.
```

`tests/test_boundaries.py` verifica as dependências: o domínio só usa a biblioteca padrão (e nada
de `os`/`pathlib`, porque não sabe onde o conteúdo mora); a application só conhece domínio e
protocolos; a infra não conhece application; só a composição importa a infra.

O domínio também não conhece o protocolo do modelo. A porta de agente é
`Agent.run(AgentRequest, ToolCatalog) -> AgentAnswer`: o domínio entrega a mensagem, a versão do
prompt e as skills, e recebe assunto e justificativa. Mensagens de chat e gateway
(`infrastructure/model/ports.py`), montagem do prompt de sistema
(`infrastructure/content/render.py`) e leitura do JSON do modelo
(`infrastructure/agents/answer.py`) ficam na infra.

## Prompts e skills

```
src/agent_sample/content/
  prompts/classify_subject/v1.md, v2.md       # templates com $subjects e $skills
  skills/subject-boundaries/v1.md             # frontmatter "description:" + corpo
  skills/out-of-scope/v1.md
  published.json                              # sha256 de cada versão publicada
```

- O domínio declara o que a tarefa pede (`CLASSIFY_TASK`: prompt `classify_subject` e as skills
  `subject-boundaries` e `out-of-scope`), sem fixar versões. Os dois agentes usam o mesmo conteúdo.
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

## Verificação

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```
