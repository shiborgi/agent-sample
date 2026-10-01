---
name: test-quality
description: Qualidade de testes - cobertura do comportamento alterado e testes que testam o que dizem.
---
Verifique:
- o comportamento alterado tem teste que falharia sem a mudança;
- casos de borda e de erro foram cobertos, não só o caminho feliz;
- o nome do teste descreve o que ele verifica, e as asserções verificam isso;
- testes não dependem de rede, relógio, ordem de execução ou estado global;
- mocks não substituem justamente o que deveria ser testado.
Classifique como `tests`. Teste que passa sem testar nada é `major`.
