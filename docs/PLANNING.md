> Histórico: planejamento do classificador de assunto, que o projeto deixou de ser. O caso de uso
> atual é o revisor de código descrito em `docs/CODE_REVIEWER.md` e no `README.md`.


# Tarefa: evoluir o agent-sample para uma arquitetura híbrida, coesa e extensível

## Contexto
O projeto classifica o assunto de uma mensagem em `billing`, `technical`, `sales` ou `other`,
exposto por CLI (Typer) e pelo protocolo A2A. Hoje todas as formas de classificar dependem de um
modelo de linguagem. Leia o código existente antes de propor mudanças e mantenha o estilo do projeto.

## O que o sistema deve oferecer

### Formas de classificar
- **Workflow determinístico:** classifica sem modelo, por regras explícitas e reproduzíveis.
  Mesma entrada, mesmo resultado.
- **Agente:** um modelo raciocina, decide sozinho quando usar ferramentas e chega a um veredito.
- **Híbrido:** tenta primeiro o caminho determinístico. Só recorre ao agente quando as regras não
  decidem. Se o agente falhar, entrega um resultado seguro em vez de erro, e registra que isso
  aconteceu.
- A forma de classificar é escolhida por quem usa, tanto na CLI quanto no A2A (por requisição,
  com um padrão do servidor).

### Qualidade do veredito
- Todo veredito informa o assunto, a justificativa, quem decidiu e o caminho percorrido até a
  decisão.
- Quando houve agente, o caminho informa também qual versão de prompt e quais skills foram usadas.
- A confiança só é informada quando existe de fato. Regras não inventam probabilidade.
- As regras não se deixam enganar por pedaços de palavras. "capital" não indica `technical` e
  "demorando" não indica `sales`. Acentos e maiúsculas não mudam o resultado.
- Empate entre assuntos, ou ausência de evidência, resulta em `other` no caminho determinístico.

### Múltiplas implementações
- Pelo menos duas formas diferentes de executar o workflow, produzindo o mesmo resultado para a
  mesma entrada.
- Pelo menos duas implementações de agente, de frameworks diferentes, que sejam agênticas de verdade.
- Implementações que não se encaixam bem em nenhuma categoria (ex.: predição de passo único) podem
  existir, desde que rotuladas com honestidade.

### Prompts e skills da camada agêntica
- O comportamento dos agentes é guiado por **prompts** e **skills** tratados como conteúdo,
  separado do código.
- Deve ser possível alterar um prompt, ou criar uma skill, sem mexer no código dos agentes.
- Prompts e skills são **versionados**:
  - uma versão publicada não muda;
  - é possível escolher qual versão usar;
  - é possível comparar versões lado a lado para a mesma mensagem.
- Todas as implementações de agente usam os mesmos prompts e skills. Trocar de framework não exige
  reescrever conteúdo.
- Skills são oferecidas ao agente de forma econômica: ele conhece o que existe e só carrega o
  conteúdo completo de uma skill quando precisa.
- Prompt, versão ou skill inválidos ou inexistentes são detectados logo na inicialização, com
  mensagem clara. Isso não pode aparecer como erro no meio de uma classificação.
- Deve ser possível listar e inspecionar os prompts e skills disponíveis.

### Uso sem modelo configurado
- O uso padrão funciona sem credencial de modelo nas mensagens que as regras resolvem.
- Nas demais, degrada de forma controlada, sem quebrar.

## Responsabilidades por camada
- **application:** CLI e A2A só traduzem entrada e saída. Não contêm regra de negócio nem conhecem
  frameworks. Os dois usam o mesmo ponto de entrada e tratam erros da mesma forma:
  - a CLI mostra uma mensagem curta e sai com código de erro, sem traceback;
  - o A2A marca a tarefa como falha e não deixa a exceção escapar.
- **domain:** decide *o que* fazer:
  - regras de classificação;
  - definição das etapas e estratégias;
  - política de escalada e fallback;
  - ferramentas disponíveis ao agente;
  - contrato do veredito;
  - quais capacidades (prompt e skills) cada tarefa agêntica pede.

  Não conhece frameworks, protocolos de LLM nem onde o conteúdo de prompts e skills é armazenado.
- **infrastructure:** decide *como* executar:
  - motores de workflow;
  - implementações de agente;
  - acesso ao modelo;
  - armazenamento, carregamento e versionamento de prompts e skills.
- **Composição:** é o único ponto que conhece as implementações concretas e as liga às abstrações.

## Extensibilidade esperada
Cada evolução abaixo deve ser localizada, sem editar código não relacionado:
- adicionar um motor de workflow;
- adicionar um agente de outro framework;
- adicionar uma ferramenta, que passa a valer para todos os agentes;
- adicionar uma estratégia de classificação;
- publicar uma nova versão de prompt;
- criar uma nova skill.

Documente no README como fazer cada uma.

## Restrições
- Faça o mínimo necessário para atingir o objetivo. Evite abstração sem uso, código morto e erro
  engolido em silêncio.
- Não quebre comandos existentes sem necessidade. Se quebrar, atualize a documentação e os testes.
- O README explica as camadas e as formas de classificar, e dá exemplos de uso.

## Critérios de aceite
1. Testes, lint e checagem de formatação do projeto passam.
2. Existe verificação automática de que as dependências entre camadas respeitam as
   responsabilidades acima.
3. Cobertura por testes de:
   - regras determinísticas;
   - estratégias, incluindo escalada e fallback;
   - equivalência entre motores de workflow;
   - cada agente, sem acesso à rede;
   - A2A ponta a ponta, em sucesso e em falha;
   - prompts e skills: validação, versões, carregamento sob demanda e rastreabilidade no veredito.
4. Sem credencial de modelo, o uso padrão da CLI classifica:
   - "Fui cobrado duas vezes" → `billing`
   - "A API retorna 500" → `technical`
   - "O suporte está demorando" → `other`
   - "Preciso de capital de giro" → `other`
   - "Erro na fatura" → `other`
   - "Bom dia" → `other`
5. Entregue tudo em um único commit no branch de trabalho.

## Entrega
Responda com:
- as decisões técnicas tomadas e o porquê;
- como prompts e skills foram modularizados e versionados;
- como cada ponto de extensão funciona;
- a saída real dos comandos de verificação;
- as limitações conhecidas.
