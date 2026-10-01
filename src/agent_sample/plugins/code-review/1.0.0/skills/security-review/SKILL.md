---
name: security-review
description: Revisão de segurança - injeção, segredos, autenticação, autorização e dados sensíveis.
---
Verifique, no código novo:
- entrada externa chegando a SQL, shell, caminhos de arquivo, templates ou desserialização sem
  validação ou parametrização (injeção, path traversal, SSRF);
- credenciais, tokens ou chaves no código, em logs ou em mensagens de erro;
- autenticação ou autorização ausente em rotas e operações novas;
- criptografia caseira, algoritmos fracos, comparação de segredos sem tempo constante;
- dados pessoais registrados em log ou enviados a terceiros.
Classifique como `security`. Exploração plausível e direta é `critical`; o resto, `major`.
