# Tarefa: adicionar um agente de code review ao agent-sample

## Contexto
O projeto já classifica mensagens com uma arquitetura híbrida (workflow determinístico, agente e
híbrido), com prompts e skills versionados e exposição por CLI e A2A. Leia o código e o
`docs/PLANNING.md` antes de começar.

Adicione um **segundo caso de uso**: um agente que revisa uma mudança de código e aponta
problemas. Ele deve reaproveitar a arquitetura existente e tudo o que já for genérico, sem
quebrar o classificador. Se algo hoje específico do classificador precisar virar genérico para
servir aos dois casos, faça essa generalização.

## O que o revisor faz

### Entrada
- Uma mudança de código em formato de diff unificado. Pode vir de texto, de arquivo ou gerada a
  partir de um repositório git local, comparando duas referências.
- Opcionalmente, o foco da revisão (ex.: segurança, testes, desempenho) e a linguagem, quando não
  for possível deduzir.
- Diff vazio ou ilegível resulta em erro claro, nunca em revisão vazia.

### Saída: a revisão
- **Decisão:** `approve`, `comment` ou `request_changes`.
- **Resumo** curto da mudança e do que foi encontrado.
- **Achados**, cada um com:
  - arquivo e linha (ou intervalo) no código novo;
  - severidade: `critical`, `major`, `minor` ou `nit`;
  - categoria: `correctness`, `security`, `performance`, `maintainability`, `tests` ou `style`;
  - descrição do problema e sugestão de correção;
  - origem: regra determinística ou agente;
  - evidência: o trecho do diff que sustenta o achado.
- **Caminho percorrido** até a revisão, como no classificador: etapas executadas, qual agente
  participou, versão do prompt e skills usadas.
- Confiança só aparece quando existe de fato. Regras não inventam probabilidade.
- A decisão segue uma regra explícita e documentada. Por exemplo: qualquer `critical` ou `major`
  resulta em `request_changes`; só `minor` ou `nit`, em `comment`; nenhum achado, em `approve`.

### Formas de revisar
- **Workflow determinístico:** checagens explícitas e reproduzíveis, sem modelo. Mesmo diff, mesma
  revisão. Checagens mínimas:
  - credenciais ou segredos no código (chaves de API, tokens, senhas);
  - resquícios de depuração (prints, breakpoints, código comentado em bloco);
  - código-fonte alterado sem nenhuma alteração de teste correspondente;
  - marcadores pendentes adicionados (TODO, FIXME);
  - arquivos grandes ou binários, que são ignorados e registrados como não revisados.
- **Agente:** um modelo lê a mudança, decide sozinho o que investigar e usa ferramentas para
  entender o contexto. Ele encontra o que regras não pegam: erro de lógica, caso de borda não
  tratado, nome enganoso, teste que não testa o que diz.
- **Híbrido (padrão):** roda o workflow primeiro e depois o agente, que recebe os achados das
  regras como contexto. O agente pode acrescentar achados, mas não remove nem rebaixa um achado
  `critical` das regras. Achados duplicados entre regras e agente aparecem uma vez só. Se o agente
  falhar, a revisão sai só com os achados das regras e registra que o agente falhou.

### Ferramentas do agente
- Ler um arquivo do repositório, ou um trecho dele, para ver o contexto além do diff.
- Buscar um símbolo ou texto no repositório.
- Listar os critérios de revisão disponíveis e carregar uma skill sob demanda.
- **Todas as ferramentas são somente leitura.** O agente nunca executa código, nunca altera
  arquivos e nunca acessa nada fora do repositório revisado.
- Há limite de rodadas de ferramenta e de tamanho de contexto. Diffs grandes são revisados em
  partes (por arquivo, por exemplo), e a revisão final junta as partes.

### Validação dos achados do agente
O resultado do agente não é aceito às cegas:
- achado em arquivo que não está no diff, ou em linha que não existe no código novo, é descartado;
- achado sem descrição ou com severidade ou categoria fora da lista é descartado;
- cada descarte fica registrado no caminho da revisão, com o motivo.

### Prompts e skills
- Seguem o mesmo modelo do classificador: conteúdo separado do código, versionado, com versão
  publicada imutável, escolha de versão, comparação lado a lado e validação na inicialização.
- Skills de revisão por tema e por linguagem, por exemplo:
  - revisão de segurança;
  - qualidade de testes;
  - boas práticas de Python.
- O agente vê só o índice das skills e carrega o conteúdo completo quando precisa.
- Criar uma skill nova, ou uma nova versão de prompt, não exige mudar código.

### Uso
- **CLI:**
  - revisa um diff (texto, arquivo ou duas referências git) e mostra a revisão legível;
  - permite escolher forma de revisar, agente, versão de prompt e skills;
  - tem saída estruturada (ex.: JSON) para integração;
  - sai com código diferente de zero quando a decisão é `request_changes`, para uso em CI;
  - erros saem como mensagem curta e código de erro, sem traceback.
- **A2A:**
  - uma skill de revisão recebe o diff e devolve a revisão;
  - opções vão por requisição, com padrões do servidor;
  - falhas marcam a tarefa como falha, sem deixar a exceção escapar.
- **Sem credencial de modelo:** o modo padrão entrega a revisão das regras e registra que o agente
  não estava disponível.

## Responsabilidades por camada
Valem as mesmas regras do `docs/PLANNING.md`:
- **application** só traduz entrada e saída;
- **domain** decide o que fazer: checagens, estratégias, política de decisão, regras de
  validação dos achados, ferramentas e contrato da revisão. Não conhece frameworks, protocolo de
  LLM, sistema de arquivos nem git;
- **infrastructure** decide como executar: motores de workflow, agentes, acesso ao modelo, leitura
  do repositório e do git, armazenamento de prompts e skills;
- **composição** é o único ponto que liga as implementações concretas.

## Extensibilidade esperada
Cada evolução abaixo deve ser localizada, sem editar código não relacionado, e estar documentada
no README:
- adicionar uma checagem determinística;
- adicionar uma skill de revisão (tema ou linguagem);
- adicionar um agente de outro framework;
- adicionar um formato de saída (ex.: comentários de pull request);
- adicionar uma ferramenta de leitura ao agente.

## Restrições
- Faça o mínimo necessário. Evite abstração sem uso, código morto e erro engolido em silêncio.
- O classificador continua funcionando e com os testes passando.
- Nenhum teste acessa a rede ou um modelo real.

## Critérios de aceite
1. Testes, lint e checagem de formatação passam, incluindo os do classificador.
2. A verificação automática de dependências entre camadas cobre o novo caso de uso.
3. Existe um conjunto de diffs de exemplo versionado no repositório, e sem credencial de modelo o
   modo padrão produz:

   | Diff de exemplo | Resultado esperado |
   |---|---|
   | adiciona uma chave de API no código | achado `critical`, `security`; decisão `request_changes` |
   | adiciona um `print` de depuração | achado `minor`; decisão `comment` |
   | altera código-fonte sem alterar testes | achado de `tests`; decisão `comment` |
   | mudança limpa, com teste correspondente | nenhum achado; decisão `approve` |
   | inclui um arquivo binário | arquivo listado como não revisado, sem erro |
   | diff vazio | erro claro e código de erro |

4. O mesmo diff revisado duas vezes no modo workflow produz exatamente a mesma saída.
5. Com agente falso, sem rede, há testes de que:
   - achados em linhas ou arquivos fora do diff são descartados e o descarte é registrado;
   - o agente não consegue remover nem rebaixar um achado `critical` das regras;
   - achados duplicados aparecem uma vez;
   - falha do agente no híbrido mantém os achados das regras e registra a falha;
   - o caminho registra a versão do prompt e as skills carregadas;
   - as ferramentas do agente não leem nada fora do repositório revisado.
6. A2A ponta a ponta, em sucesso e em falha.
7. A CLI sai com código diferente de zero quando a decisão é `request_changes`.
8. Entregue tudo em um único commit no branch de trabalho.

## Entrega
Responda com:
- as decisões técnicas tomadas e o porquê;
- o que foi generalizado para servir aos dois casos de uso;
- como os achados do agente são validados;
- como cada ponto de extensão funciona;
- a saída real dos comandos de verificação;
- as limitações conhecidas.
