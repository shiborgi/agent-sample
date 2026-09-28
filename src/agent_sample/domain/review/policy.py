"""Limites da revisão: o que é grande demais e quanto o agente pode ler e investigar."""

# Arquivo com mais linhas alteradas que isso, ou com diff maior que MAX_PART_CHARS, não é revisado.
MAX_FILE_LINES = 1000
# Tamanho máximo do diff enviado ao agente de uma vez; diffs maiores são revisados em partes.
MAX_PART_CHARS = 30_000
# Rodadas de ferramenta por parte.
MAX_REVIEW_TOOL_ROUNDS = 8
# Tamanho máximo do que uma ferramenta devolve ao agente.
MAX_TOOL_OUTPUT_CHARS = 8_000
MAX_READ_LINES = 200
MAX_SEARCH_HITS = 30
