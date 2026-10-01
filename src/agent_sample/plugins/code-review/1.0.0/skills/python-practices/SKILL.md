---
name: python-practices
description: Boas práticas de Python - exceções, tipos, recursos, mutabilidade e APIs assíncronas.
---
Verifique, em código Python:
- `except` amplo que engole erro, ou exceção relançada sem `from`;
- argumento padrão mutável (`def f(x=[])`);
- recursos sem `with` (arquivos, locks, conexões);
- chamadas bloqueantes dentro de `async def`;
- tipos inconsistentes com o uso, `Any` desnecessário, `None` não tratado;
- comparação com `is` para valores (`is 0`, `is ""`).
Use `correctness` para bugs e `maintainability` ou `style` para o resto.
