# agent-sample

Classifica o assunto de uma mensagem. Typer e A2A só traduzem texto. O domain devolve um `Verdict`. LangGraph, DeepAgents e Laya implementam o mesmo classificador na infra.

```bash
uv sync
uv run subject classify "Fui cobrado duas vezes" --runtime langgraph
uv run subject compare "A API retorna 500"
CLASSIFIER=laya uv run subject-a2a
```

`MODEL_BASE_URL`, `MODEL_API_KEY` e `MODEL_NAME` alimentam o gateway OpenAI-compatible usado por LangGraph e DeepAgents. Laya não usa esse gateway: um forward pass escolhe o assunto. O extra é `uv sync --extra laya`.

Assuntos fechados: `billing`, `technical`, `sales`, `other`.
