---
name: django-security
description: Riscos de segurança comuns em Django - raw SQL, mark_safe, CSRF, DEBUG e ALLOWED_HOSTS.
---
Verifique, em código Django:
- `raw()`, `extra()` ou `cursor.execute` com interpolação de string;
- `mark_safe`/`|safe` em conteúdo vindo do usuário;
- `@csrf_exempt` em views que alteram estado;
- `DEBUG = True` ou `ALLOWED_HOSTS = ["*"]` em configuração de produção.
Classifique como `security`.
