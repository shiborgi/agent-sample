# Tarefa: transformar o agent-sample em um agente de code review (CLI e A2A)

## Contexto
Hoje o projeto classifica o assunto de mensagens com workflow determinístico, agentes e um modo
híbrido, com prompts e skills versionados, expostos por CLI (Typer) e A2A. Leia o código, o
`docs/PLANNING.md` e o `docs/CODE_REVIEW_AGENT.md` antes de começar.

O objetivo agora é que o projeto **passe a ser** um agente de code review. O classificador deixa
de ser o caso de uso e pode ser removido. Reaproveite o que já é genérico (camadas, composição,
tratamento de erros, conteúdo versionado, A2A, CLI) e simplifique o resto.

Esta especificação é funcional: descreve o que o sistema faz e as regras que ele respeita, não
como implementar.

## Princípios
- **Camadas mantidas:** `application`, `domain`, `infrastructure` e um único ponto de composição.
- **Domínio agnóstico de framework:** o domínio descreve a revisão e suas regras. Não sabe que
  existe DeepAgents, LangGraph, A2A, Typer, HTTP, git, sistema de arquivos, formato `SKILL.md` ou
  manifesto de plugin.
- **Simplicidade antes de variedade:** uma implementação de cada coisa, a menos que a segunda
  resolva um problema real. Não é requisito ter dois motores de workflow nem dois frameworks de
  agente; é requisito que trocar um deles seja uma mudança localizada.
- **Workflow híbrido:** o fluxo é determinístico de ponta a ponta, e a parte agêntica é uma etapa
  dentro dele, com entrada, saída, limites e falha bem definidos.
- **Conteúdo e capacidades são externos ao código:** critérios de revisão, revisores especializados
  e prompts chegam como skills e plugins importáveis, não como código do projeto.

## O que o revisor faz

### Entrada: a mudança
- A mudança pode vir de:
  - diff unificado em texto ou arquivo;
  - repositório git local, comparando duas referências;
  - um pull request remoto, identificado por URL ou por repositório e número (via cliente REST).
- Opcionalmente: foco da revisão (ex.: segurança, testes, desempenho), linguagem, e quais plugins
  ou skills usar.
- Diff vazio, ilegível ou referência inexistente resulta em erro claro, nunca em revisão vazia.
- Arquivos binários, gerados ou acima do limite de tamanho não são revisados; ficam listados como
  "não revisados", com o motivo.

### Saída: a revisão
- **Decisão:** `approve`, `comment` ou `request_changes`, seguindo uma regra explícita e
  documentada (ex.: qualquer `critical` ou `major` → `request_changes`; só `minor` ou `nit` →
  `comment`; nenhum achado → `approve`).
- **Resumo** curto da mudança e do que foi encontrado.
- **Achados**, cada um com:
  - arquivo e linha (ou intervalo) no código novo;
  - severidade: `critical`, `major`, `minor` ou `nit`;
  - categoria: `correctness`, `security`, `performance`, `maintainability`, `tests` ou `style`;
  - descrição e sugestão de correção;
  - origem: checagem determinística (qual) ou agente (qual revisor e qual skill);
  - evidência: o trecho do diff que sustenta o achado.
- **Arquivos não revisados**, com o motivo.
- **Caminho percorrido:** etapas executadas, com resultado de cada uma; agentes e revisores
  acionados; versões de prompt, skills e plugins usados; chamadas a ferramentas; achados
  descartados na validação e o motivo; falhas e degradações.
- Confiança só aparece quando existe de fato. Nem regras nem agentes inventam probabilidade.

## Workflow híbrido

O domínio define as etapas, a ordem e o que cada uma pode fazer. Um motor de workflow só as
executa. As etapas mínimas são:

| # | Etapa | Natureza | Responsabilidade |
|---|---|---|---|
| 1 | Obter a mudança | determinística | Ler o diff da fonte escolhida (texto, arquivo, git, PR remoto). |
| 2 | Normalizar | determinística | Separar arquivos e trechos, detectar linguagem, marcar o que não será revisado. |
| 3 | Checagens | determinística | Rodar as checagens explícitas sobre a mudança. |
| 4 | Planejar | determinística | Decidir se a etapa agêntica roda, sobre quais partes e com quais revisores e skills. |
| 5 | Revisão agêntica | **agêntica** | Revisores investigam a mudança com ferramentas e propõem achados. |
| 6 | Validar | determinística | Aceitar ou descartar cada achado proposto, registrando o motivo. |
| 7 | Consolidar | determinística | Juntar achados, remover duplicados, preservar achados das checagens. |
| 8 | Decidir | determinística | Aplicar a política de decisão e montar o resumo. |
| 9 | Publicar | determinística | Entregar a revisão no formato pedido; opcionalmente comentar no PR remoto. |

Regras do fluxo:
- **Modos de revisão**, escolhidos por quem usa:
  - `workflow`: só etapas determinísticas; a etapa 5 não roda. Mesma mudança, mesma revisão.
  - `hybrid` (padrão): todas as etapas.
  - `agent`: a etapa 3 não roda, mas as etapas 6 a 8 continuam valendo. O agente nunca decide a
    revisão final sozinho.
- A etapa agêntica recebe os achados das checagens como contexto e não pode remover nem rebaixar
  um achado `critical` vindo delas.
- Achados duplicados entre checagens e agente aparecem uma vez só, preservando a origem de maior
  severidade.
- Se a etapa agêntica falhar ou estourar limites, a revisão sai com os achados determinísticos e o
  caminho registra a falha. A falha não vira erro da revisão.
- A decisão de acionar ou não o agente (etapa 4) segue regra explícita, por exemplo: mudança só
  de documentação ou só de arquivos não revisáveis não aciona o agente.
- Mudanças grandes são divididas em partes (ex.: por arquivo). Cada parte é revisada dentro dos
  limites e a consolidação junta o resultado.
- Toda escrita externa (comentar no PR, publicar status) acontece só na etapa 9, que é
  determinística. O agente nunca escreve em sistema externo.

### Checagens determinísticas mínimas
- credenciais ou segredos no código (chaves de API, tokens, senhas);
- resquícios de depuração (prints, breakpoints, blocos de código comentado);
- código-fonte alterado sem alteração de teste correspondente;
- marcadores pendentes adicionados (TODO, FIXME);
- arquivos grandes, binários ou gerados, registrados como não revisados.

Adicionar uma checagem não exige mexer em outras etapas.

## Revisão agêntica com Deep Agents

- A etapa agêntica usa Deep Agents como implementação de referência: um revisor principal que
  planeja, carrega skills sob demanda e pode delegar para revisores especializados (subagentes),
  por exemplo segurança, testes e uma linguagem específica.
- O domínio vê essa etapa por uma porta própria: recebe a mudança normalizada, os achados das
  checagens, o plano (revisores e skills escolhidos) e as ferramentas permitidas; devolve achados
  propostos e o registro do que foi feito (revisores acionados, skills carregadas, ferramentas
  chamadas). Mensagens de chat, formato de tool call, grafo e middleware ficam na infra.
- Trocar Deep Agents por outro framework é implementar essa porta e registrá-la na composição,
  sem mudar domínio, skills ou plugins.
- Limites explícitos e configuráveis: rodadas de ferramenta, tempo total, tamanho de contexto,
  número de subagentes acionados.
- Recursos do framework que executam código, escrevem arquivos ou acessam rede fora das
  ferramentas permitidas ficam desligados.

### Validação dos achados propostos
O resultado do agente nunca é aceito às cegas. Um achado é descartado quando:
- aponta arquivo que não está na mudança, ou linha que não existe no código novo;
- não tem descrição, ou tem severidade ou categoria fora da lista;
- não traz evidência que exista no diff.

Cada descarte fica no caminho da revisão, com o motivo.

## Skills e agent-plugins

### Skills
- Seguem o formato de Agent Skills: uma pasta por skill com um `SKILL.md` (frontmatter com `name`
  e `description`, e corpo com as instruções) e arquivos de apoio opcionais.
- O agente recebe só o índice (nome e descrição) e carrega o conteúdo completo quando precisa.
- Exemplos esperados: revisão de segurança, qualidade de testes, boas práticas de Python, e o
  prompt do revisor principal.

### Agent-plugins
Um plugin é um pacote de capacidades de revisão que pode ser importado sem mudar o código do
projeto. Ele pode conter:
- skills;
- revisores especializados (subagentes): nome, descrição de quando acionar, instruções, skills e
  ferramentas que podem usar;
- metadados: nome, versão, descrição, autor, compatibilidade com a versão do revisor.

Plugins **não contêm código executável**. Um revisor de plugin só pode referenciar ferramentas que
já existem no catálogo do projeto; referência a ferramenta desconhecida invalida o plugin. Isso
mantém ferramentas (e seus riscos) sob controle do projeto, e plugins como conteúdo.

O formato do plugin deve ser compatível, sempre que possível, com o formato de plugins do
ecossistema de agentes (manifesto do plugin, pasta `skills/`, pasta `agents/`), para que o mesmo
plugin sirva a este revisor e a outras ferramentas.

### Importação modular
- Plugins e skills vêm de **fontes** declaradas em configuração, não em código:
  - diretório local;
  - pacote Python instalado que declara plugins;
  - repositório git remoto fixado em uma referência imutável (commit ou tag).
- Existe um **lock** das fontes: o que foi resolvido, de onde, em qual versão e com qual hash.
  Conteúdo que diverge do lock falha a inicialização.
- Ordem de precedência explícita entre fontes (ex.: embutido → usuário → projeto). Nome repetido
  segue a precedência e o conflito aparece na listagem; nunca é resolvido em silêncio.
- Plugins podem ser habilitados ou desabilitados por configuração e escolhidos por requisição.
- Tudo é validado na inicialização: manifesto, frontmatter, nomes, versões, referências a skills e
  a ferramentas, compatibilidade. Erro de conteúdo nunca aparece no meio de uma revisão.
- Conteúdo publicado é imutável, como no modelo atual de prompts e skills: é possível escolher
  versão e comparar versões lado a lado para a mesma mudança.
- O projeto traz seus próprios critérios de revisão como um plugin embutido, carregado pelo mesmo
  mecanismo que os externos.

### Pontos a validar e registrar na entrega
- Se o carregamento nativo de skills e subagentes do Deep Agents atende a importação modular
  (fontes, precedência, lock, validação na inicialização) ou se a infra resolve as fontes e entrega
  ao framework só o conteúdo já validado. A escolha precisa manter o domínio sem conhecer o formato.
- Como versão de plugin, versão de skill e rastreabilidade no caminho da revisão se relacionam.
- O que do formato de plugin do ecossistema é suportado e o que é ignorado (com aviso).

## Ferramentas e cliente REST

### Ferramentas do agente
- Todas **somente leitura** e restritas à mudança revisada:
  - ler um arquivo do repositório, ou um trecho dele;
  - buscar um símbolo ou texto no repositório;
  - listar arquivos de um diretório;
  - consultar o histórico de um trecho (ex.: blame);
  - carregar uma skill;
  - obter contexto remoto do PR via REST: descrição, issues ligadas, status de CI, comentários
    anteriores.
- O domínio define o contrato de cada ferramenta (nome, descrição, parâmetros, o que pode
  acessar). A infra define como executa. Uma ferramenta nova vale para todos os revisores que a
  referenciarem.
- Nenhuma ferramenta acessa nada fora do repositório revisado ou dos hosts permitidos.
- Saída de ferramenta tem tamanho limitado; o excesso é truncado com aviso.

### Cliente REST
- Usado em dois papéis distintos:
  - **fonte e destino determinísticos** (etapas 1 e 9): obter o diff e os metadados de um PR;
    publicar a revisão como comentários no PR;
  - **ferramenta do agente** (etapa 5): só leitura de contexto.
- O domínio conhece apenas portas com significado de revisão (ex.: obter mudança, obter contexto
  do PR, publicar revisão), nunca URL, verbo HTTP, cabeçalho ou payload do provedor.
- Pelo menos um provedor (ex.: GitHub) implementado; adicionar outro (ex.: GitLab) é uma mudança
  localizada na infra e na composição.
- Regras do cliente: hosts permitidos por configuração, credencial vinda do ambiente e nunca
  registrada em log ou no caminho, tempo limite, novas tentativas limitadas só em erros
  transitórios, e erro traduzido para mensagem clara.
- Publicar no PR exige pedido explícito de quem usa. O padrão é só devolver a revisão.

### Pontos a validar e registrar na entrega
- Se as ferramentas REST devem ser expostas ao agente diretamente ou se o contexto remoto deve ser
  obtido de forma determinística na etapa 1 e entregue pronto. Critério: previsibilidade, custo e
  rastreabilidade.
- Se alguma ferramenta pode vir de um servidor MCP externo, mantendo a regra de somente leitura e
  de catálogo controlado pelo projeto.

## Uso

### CLI
- `review`: revisa um diff (texto, arquivo, duas referências git ou PR remoto) e mostra a revisão
  legível. Permite escolher modo, plugins, skills, versões e formato de saída.
- Formatos de saída: legível, JSON e comentários de PR.
- `--post` publica no PR remoto; sem ele nada é escrito fora do processo.
- `plugins list | show | validate` e `skills list | show`: listam e inspecionam o conteúdo
  carregado, com fonte, versão e conflitos.
- Código de saída diferente de zero quando a decisão é `request_changes`, para uso em CI, e outro
  código distinto para erro.
- Erros saem como mensagem curta, sem traceback.

### A2A
- O agent card anuncia a skill de code review e as capacidades vindas dos plugins habilitados.
- A requisição traz a mudança (diff ou referência de PR) e opções em metadata; o que faltar usa o
  padrão do servidor.
- O progresso por etapa é reportado como atualização de status da tarefa.
- A revisão final volta como artefato estruturado e como texto legível.
- Falhas marcam a tarefa como falha, sem deixar a exceção escapar.

### Sem credencial de modelo
O modo padrão entrega a revisão determinística e registra que a etapa agêntica não estava
disponível. `--mode agent` falha com mensagem clara.

## Responsabilidades por camada
- **application:** CLI e A2A só traduzem entrada e saída e chamam um único serviço de revisão.
  Não contêm regra de negócio e não conhecem framework de agente, git, HTTP nem formato de plugin.
- **domain:** decide *o que* fazer:
  - modelo da revisão (mudança, arquivo, trecho, achado, decisão, caminho);
  - etapas do workflow e o que cada uma pode fazer;
  - checagens determinísticas;
  - plano da etapa agêntica e seus limites;
  - política de validação, consolidação e decisão;
  - contrato das ferramentas e das portas (fonte da mudança, contexto remoto, publicação,
    revisão agêntica, catálogo de capacidades);
  - conceitos de skill, revisor e plugin como capacidades com nome, descrição e versão.

  Regras: só biblioteca padrão; sem acesso a arquivo, rede, git, ambiente ou relógio; sem tipos de
  framework nas assinaturas; sem conhecimento de onde ou em que formato o conteúdo mora.
- **infrastructure:** decide *como* executar: motor de workflow, Deep Agents, acesso ao modelo,
  git, cliente REST, leitura do repositório, resolução e validação de fontes de plugins e skills,
  formatos de saída.
- **composição:** único ponto que conhece as implementações concretas e as liga às portas.

## Simplificações esperadas
- Remover o classificador, a estratégia de predição e o que existia só para ele.
- Um motor de workflow e um framework de agente, atrás das portas. Uma segunda implementação só
  entra se trouxer ganho concreto, e deve ser justificada na entrega.
- Substituir o modelo próprio de prompts e skills pelo formato de skills e plugins, mantendo
  versionamento, imutabilidade e validação na inicialização.
- Evitar abstração sem uso, código morto e erro engolido em silêncio.

## Extensibilidade esperada
Cada evolução abaixo deve ser localizada, sem editar código não relacionado, e estar documentada
no README:
- adicionar uma checagem determinística;
- adicionar uma skill ou um revisor especializado, dentro de um plugin;
- importar um plugin externo (diretório, pacote ou git);
- adicionar uma ferramenta de leitura;
- adicionar um provedor REST de pull requests;
- adicionar um formato de saída;
- trocar o framework da etapa agêntica.

## Restrições
- Nenhum teste acessa a rede ou um modelo real.
- Nenhuma ferramenta do agente escreve, executa código ou sai do repositório revisado.
- Credenciais nunca aparecem em log, no caminho da revisão nem na saída.

## Critérios de aceite
1. Testes, lint e checagem de formatação passam.
2. A verificação automática de dependências entre camadas cobre as regras acima, incluindo a
   ausência de frameworks, I/O e formato de conteúdo no domínio.
3. Existe um conjunto de diffs de exemplo versionado, e sem credencial de modelo o modo padrão
   produz:

   | Diff de exemplo | Resultado esperado |
   |---|---|
   | adiciona uma chave de API no código | achado `critical`, `security`; decisão `request_changes` |
   | adiciona um `print` de depuração | achado `minor`; decisão `comment` |
   | altera código-fonte sem alterar testes | achado de `tests`; decisão `comment` |
   | mudança limpa, com teste correspondente | nenhum achado; decisão `approve` |
   | inclui um arquivo binário | arquivo listado como não revisado, sem erro |
   | diff vazio | erro claro e código de erro |

4. A mesma mudança revisada duas vezes no modo `workflow` produz exatamente a mesma saída.
5. Com agente falso, sem rede, há testes de que:
   - achados fora do diff, sem evidência ou fora das listas são descartados e registrados;
   - o agente não remove nem rebaixa um achado `critical` das checagens;
   - achados duplicados aparecem uma vez;
   - falha ou estouro de limite do agente mantém os achados determinísticos e registra a falha;
   - o caminho registra revisores, skills, plugins e versões usados;
   - as ferramentas não leem nada fora do repositório revisado.
6. Plugins e skills:
   - um plugin de exemplo externo ao pacote é importado por configuração, sem mudar código;
   - plugin com manifesto inválido, skill inexistente, ferramenta desconhecida ou conteúdo
     divergente do lock falha na inicialização com mensagem clara;
   - conflito de nomes entre fontes segue a precedência e aparece na listagem.
7. Cliente REST com servidor falso: obter PR, erro de autenticação, erro transitório com nova
   tentativa, host não permitido e publicação só com `--post`.
8. A2A ponta a ponta, em sucesso e em falha, incluindo atualização de status por etapa.
9. A CLI sai com código diferente de zero quando a decisão é `request_changes`.
10. Entregue tudo em um único commit no branch de trabalho.

## Entrega
Responda com:
- as decisões técnicas tomadas e o porquê, incluindo as respostas aos "pontos a validar";
- o que foi removido ou simplificado em relação ao classificador;
- como plugins e skills são importados, versionados e validados;
- quais etapas são determinísticas e quais agênticas, e como a fronteira é garantida;
- como cada ponto de extensão funciona;
- a saída real dos comandos de verificação;
- as limitações conhecidas.
