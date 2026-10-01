# Planejamento: executor simples de agent plugins (harness)

## Objetivo

Um projeto separado e menor que o agent-sample, com a mesma estrutura em camadas
(`application`, `domain`, `infrastructure` + um único ponto de composição), cujo único caso de
uso é: **dado um zip com a estrutura de um plugin no formato Agent Plugins v1
(agent-plugins.org), instalar, declarar e executar esse plugin como um agente — receber um input
e devolver um output.**

É o "modo simple agent" aprovado: sem workflow de revisão, sem checagens determinísticas, sem
validação de achados, sem A2A na v1. Só `zip → agente → input → output`, com skills (inclusive
scripts Python das skills) e MCPs configurados no próprio plugin.

## Não-objetivos

- Não é um revisor de código: nada das 9 etapas, modos, decisão `approve/comment/request_changes`.
- Não gerencia múltiplas fontes com precedência (builtin → usuário → projeto) nem pinagem de
  versões: um plugin instalado por vez, identificado por nome; reinstalar com hash diferente exige
  novo consentimento.
- Não implementa transporte MCP `stdio` na v1 (decisão registrada abaixo).
- Não executa nada sem consentimento explícito na instalação.

## Entrada e saída

- **Entrada**: caminho de um `.zip` (ou diretório já desempacotado, ou URL que entrega um zip),
  mais o input do usuário (texto, arquivo ou stdin) e opções (`--plugin`, `--format`).
- **Saída**: o texto final do agente; opcionalmente JSON com o output mais o registro do que foi
  usado (skills carregadas, ferramentas MCP chamadas, notices).
- Erro claro e curto quando o zip não é um plugin válido, quando um servidor MCP não conecta ou
  quando o modelo não está configurado. Código de saída diferente de zero em erro.

## Mapeamento funcional (agent-sample → harness)

Cada linha diz o que a peça vira no projeto simples: **mantém**, **simplifica** ou **corta**.

| Estrutura do agent-sample | No harness | Como |
|---|---|---|
| `domain/` stdlib-only, sem framework/IO | **mantém** | O domínio continua puro: modelo do pacote (`Plugin`, `Skill`, `McpServer`), pedido de execução, erros tipados. Nada de `deepagents`, `httpx`, `typer` no domínio |
| `domain/ports.py` (portas com significado) | **mantém, menor** | Portas: `PluginSource` (zip/dir/url → diretório instalado), `SkillIndex` (índice + carga sob demanda), `ToolCatalog` (ferramentas MCP como contrato), `AgentRunner` (input → output). Sem portas de revisão (checks, fontes de diff, publishers) |
| `AgentReviewer` (etapa agêntica do review) | **simplifica** → `AgentRunner` | Em vez de `AgentTask → AgentOutcome` com contrato JSON de achados, a porta recebe `(prompt do plugin, skills, ferramentas, limites)` e devolve `(texto final, registro de uso)`. Sem validação de formato na saída |
| `CatalogGuard` (enjaula o framework) | **inverte** | No review ele esconde `write_file`/`execute`; aqui o `execute` é permitido de propósito (é assim que scripts Python das skills rodam), confinado pelo consentimento no install. O guard continua existindo para registrar limites (rodadas, timeout) e recusar o que o plugin não declarou |
| Plugins como conteúdo (`format.py`, `digest`, lock sha256) | **mantém o essencial** | Validação de `plugin.json` fechado (§5.2), nome (§5.5), descoberta em local fixo (`skills/`, `mcp.json`), contenção de paths (§4.1.3), lock com hash da árvore. Sem precedência multi-fonte, sem `package`/`git` como fonte, sem plugin embutido |
| `sources.py` (dir/package/git + lock) | **simplifica** → `installer` | Uma fonte só: o zip instalado. `install` desempacota, valida, grava lock; `run` verifica o lock e pede reconsentimento se o hash mudou |
| Skills (`SKILL.md`, índice + `load_skill`) | **mantém via nativo** | Em vez do índice próprio + ferramenta `load_skill`, usa o `SkillsMiddleware` nativo do DeepAgents (`skills=[<root>/skills]`), que já faz progressive disclosure no formato Agent Skills. O domínio registra quais skills foram carregadas a partir do trace do framework |
| Revisores/subagentes de plugin (`agents/`) | **corta na v1** | Agent Plugins v1 não padroniza `agents/` (é extensão de cliente). Na v1 o harness é skills-only + MCP; subagentes entram depois via namespace de extensão próprio, se preciso |
| `mcp.json` (ignorado com aviso no review) | **implementa (só `streamable-http`)** | Adaptador `langchain-mcp-adapters`: URL absoluta HTTPS (HTTP só loopback), sem userinfo/fragment, headers literais. Entrada inválida é pulada com aviso; servidor que não conecta não derruba o plugin (§7.2.2). Sem `stdio`: sem subprocesso gerenciado, sem `PLUGIN_ROOT`/`PLUGIN_DATA` de servidor, sem `command`/`cwd`/`env` |
| Scripts Python das skills (`skills/*/scripts/`) | **permite com consentimento** | Rodam pela ferramenta `execute` do agente, na máquina do usuário. O install lista todos os scripts encontrados e o usuário confirma. Sem sandbox na v1 (decisão de segurança abaixo) |
| `composition.py` (fiação única) | **mantém** | Um `bootstrap()` que liga installer → catálogo MCP → runner → CLI. Trocar o framework do agente ou o transporte MCP continua sendo mudança de 1 registro |
| `application/cli` (Typer) | **mantém, menor** | `install <zip\|url\|dir>`, `list`, `show <plugin>`, `run <plugin> [--input -] [--format]` |
| A2A, formatos `pr-comments`, `compare`, saída por etapa | **corta na v1** | |
| Testes sem rede/modelo real | **mantém** | Servidor MCP streamable-http falso, plugin zip de fixture, gateway de modelo roteirizado |

## Fluxo

1. **`install`**: baixa (se URL) → desempacota em `<plugins>/<nome>` → valida `plugin.json`
   (schema fechado, nome, `$schema` reconhecido) → recusa paths fora do root (symlinks inclusos) →
   descobre skills e servidores MCP → **tela de consentimento**: skills, scripts `.py` encontrados,
   servidores MCP (nomes, URLs, hosts) → confirmação → grava lock `{nome, versão, sha256,
   servidores}`.
2. **`run`**: confere o lock (hash diferente → pede reconsentimento antes de executar) → conecta
   nos servidores MCP `streamable-http` (falha isolada por servidor, com aviso) → monta o agente
   (`skills=[...]`, `tools=<mcp>`, `system_prompt` da descrição do plugin) → `ainvoke` com o input
   → devolve a última mensagem (+ registro de uso em `--format json`).
3. **`list`/`show`**: plugins instalados com versão, hash do lock, skills e servidores.

## Conformidade Agent Plugins v1 (piso mínimo, §11.1)

- Carrega plugin de um diretório (o zip é detalhe do installer; em disco vale o diretório).
- Seleciona o schema pelo `$schema` sem buscar nada na rede; rejeita versão não suportada.
- Manifesto fechado: campo top-level desconhecido é reportado e ignorado; qualquer outra
  violação rejeita o plugin sem executar nada.
- Namespaces de `extensions` não implementados são ignorados sem validação.
- Descoberta só em local fixo; local ausente não é erro; `skills/` que não é diretório ou
  `mcp.json` que não é arquivo invalida só aquele tipo.
- Suporta os dois tipos (skills + MCP) com pelo menos um transporte (`streamable-http`).
- Falha isolada: servidor MCP inválido, não suportado ou fora do ar não impede skills nem outros
  servidores; tudo é reportado, nada é silencioso.

## Segurança (modelo aprovado: confirmação no install)

- Scripts de skill e ferramentas MCP remotas são execução/código de terceiros: o install mostra
  **o que** executa (scripts, comandos não há em `streamable-http`, hosts contatados) e **quem**
  assina (autor do manifesto, origem do zip/URL).
- Reinstalar conteúdo com hash diferente do lock exige nova confirmação explícita.
- Sem sandbox na v1: documentado como limitação; o usuário executa plugins de autores em quem
  confia, como `npm install`. Sandbox (contêiner/subprocesso isolado) é evolução prevista, não
  requisito.
- Credenciais de MCP remoto (se um dia necessárias) são do cliente via ambiente, nunca do pacote.

## CLI (v1)

- `harness install <zip|url|dir> [--name <nome>] [--yes]` — instala com consentimento.
- `harness list` — instalados, versão, hash curto, servidores.
- `harness show <plugin>` — manifesto, skills (nome + descrição), servidores MCP, warnings.
- `harness run <plugin> [--input <arquivo|->] [--format text|json]` — executa; sem `--input`, lê
  stdin.
- Códigos: `0` ok, `1` erro de uso/plugin, `2` falha de execução (modelo/MCP).

## Testes (v1, sem rede nem modelo real)

- Plugin fixture em zip: `plugin.json` mínimo + 2 skills (uma com `scripts/`) + `mcp.json` com 2
  servidores.
- Servidor MCP `streamable-http` falso (ferramenta `echo` + ferramenta que falha).
- Casos: manifesto inválido/nome inválido/escape de path falham no install; servidor fora do ar
  degrada com aviso; hash mudado exige reconsentimento; skills carregadas e tools chamadas
  aparecem no `--format json`; gateway roteirizado devolve output sem rede.

## Fora da v1

MCP `stdio`, subagentes de plugin, A2A, precedência multi-fonte e pinagem de versão, sandbox de
execução, cache de ferramentas MCP, `compare` entre versões de plugin.

## Critérios de aceite

1. `install` de um zip válido instala, mostra consentimento e grava lock; de um zip inválido
   (manifesto, nome, path escape, `mcp.json`) falha com mensagem curta.
2. `run` sem modelo configurado falha claro; com gateway falso, input → output sem rede.
3. Servidor MCP fora do ar: o run completa com as demais capacidades + aviso visível.
4. Skills do plugin são carregadas sob demanda (índice no prompt, corpo via ferramenta) e o
   registro cita quais foram usadas.
5. Script Python da skill executa via `execute` somente após consentimento no install.
6. Testes, lint e formatação passam; verificação de fronteiras entre camadas cobre o domínio
   puro (mesmo padrão `test_boundaries.py` do agent-sample).
