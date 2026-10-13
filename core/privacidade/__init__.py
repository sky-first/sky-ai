"""Regras para não guardar dados do cliente.

Princípio (Lucas, 13/10/2026): nunca guardamos linhas do cliente. O SQL corre
no servidor do cliente; guardamos só o que a plataforma gera (respostas, SQL,
metadados) e o que é sensível vai cifrado. Ver ``docs/dados-do-cliente.md``.

- ``cache_semantico`` — a cache guarda resposta + SQL, nunca as linhas; num
  acerto que precisa de linhas, volta a correr o SQL na fonte do cliente.
- ``registo`` — limpa os logs de valores do cliente e de credenciais.
- ``observabilidade`` — máscara para o que segue para o Langfuse.
"""
