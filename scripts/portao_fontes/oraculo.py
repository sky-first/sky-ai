# -*- coding: utf-8 -*-
"""O «modelo ideal», limitado ao que o prompt lhe mostra.

Sem modelo real à mão (Bedrock exige ``aws sso login``), o oráculo mede o
TECTO ESTRUTURAL do caminho multi-ligação: se até um modelo que escreve
sempre o SQL certo falha, a culpa é da arquitectura e não do modelo.

Regras do oráculo — iguais às de um modelo competente e obediente:

1. Só usa as tabelas que o prompt do especialista lhe mostra (o bloco
   ``Table schema(s):``). Com uma fatia por ligação vê as tabelas todas da
   sua ligação; com uma fatia por tabela (a arquitectura antiga) vê uma.
2. Obedece ao ``LIMIT`` que o prompt exige («ALWAYS end with LIMIT N»).
   É exactamente o que um modelo bom faz — e é por isso que o corte apanha.
3. O merger só vê os ``dataset_i`` e as suas colunas; as receitas usam
   ``{t:coluna}`` e o oráculo resolve-o pelo conjunto que tem a coluna.
4. Qualquer outra chamada (correcção de SQL, título…) recebe ``IMPOSSIBLE``
   — o oráculo não «salva» o pipeline por fora das regras.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from scripts.portao_fontes.fixtures import LIGACAO_CLIENTE, tabelas
from scripts.portao_fontes.perguntas import PERGUNTAS, Pergunta


class _Resp:
    def __init__(self, content: str):
        self.content = content


_POR_LOGICO = {t.logical_name: t for t in tabelas()}


class Oraculo:
    def __init__(self, arquitectura: str = "nova") -> None:
        # «nova»: uma fatia por ligação; «antiga»: uma por tabela (main).
        self.arquitectura = arquitectura
        self.chamadas: List[Dict[str, str]] = []

    # ── utilitários ───────────────────────────────────────────────────
    @staticmethod
    def _pergunta(texto: str) -> Optional[Pergunta]:
        for p in PERGUNTAS:
            if p.texto in texto:
                return p
        return None

    @staticmethod
    def _visiveis(user: str, p: Pergunta) -> List[str]:
        bloco = user.split("Table schema(s):", 1)[-1]
        bloco = bloco.split("MULTI-SOURCE SLICE CONTRACT", 1)[0]
        # Só os cabeçalhos «Table: <físico>» — as descrições das colunas
        # citam outras tabelas («= ops.routes.origin») e não as tornam visíveis.
        cabecalhos = set(re.findall(r"^Table: (\S+)", bloco, re.M))
        return [n for n in p.tabelas if _POR_LOGICO[n].physical_name in cabecalhos]

    @staticmethod
    def _limite(sistema: str) -> Optional[int]:
        m = re.search(r"LIMIT (\d+)", sistema)
        return int(m.group(1)) if m else None

    @staticmethod
    def _resolver(sql: str, user: str) -> str:
        conjuntos: Dict[str, List[str]] = {}
        for alias, cols in re.findall(
            r"--- TABLE '(dataset_\d+)' ---.*?Columns: \[(.*?)\]", user, re.S
        ):
            conjuntos[alias] = [c.strip().strip("'\"") for c in cols.split(",")]

        def troca(m):
            col = m.group(1)
            for alias, cols in conjuntos.items():
                if col in cols:
                    return alias
            return f"dataset_sem_{col}"

        return re.sub(r"\{t:(\w+)\}", troca, sql)

    # ── a interface dos fornecedores ──────────────────────────────────
    def invoke(self, mensagens, **_):
        sistema = mensagens[0]["content"] if mensagens else ""
        user = mensagens[-1]["content"] if mensagens else ""
        tudo = "\n".join(m.get("content", "") for m in mensagens)
        p = self._pergunta(tudo)
        resposta = "IMPOSSIBLE: oraculo sem receita"
        if p is None:
            pass
        elif "routing assistant" in sistema:
            resposta = ", ".join(p.tabelas)
        elif "DuckDB SQL" in sistema:
            receita = p.merger if self.arquitectura == "nova" else p.merger_por_tabela
            resposta = "```sql\n" + self._resolver(receita, user) + "\n```"
        elif "Table schema(s):" in user and "SQL fixer" not in sistema:
            vis = self._visiveis(user, p)
            sql = None
            if "MULTI-SOURCE SLICE CONTRACT" in user:
                lado = (
                    "cliente"
                    if any(
                        _POR_LOGICO[n].data_connection_id == LIGACAO_CLIENTE
                        for n in vis
                    )
                    else "mundo"
                )
                sql = p.fatias.get(lado)
            elif len(vis) == 1:
                sql = p.por_tabela.get(vis[0])
            if sql:
                lim = self._limite(sistema)
                sql = " ".join(sql.split())
                if lim:
                    sql += f" LIMIT {lim}"
                resposta = f"-- TITLE: {p.id}\n{sql}"
        self.chamadas.append({"sistema": sistema[:120], "resposta": resposta[:300]})
        return _Resp(resposta)

    def stream(self, mensagens, **kw):  # pragma: no cover - não usado
        yield self.invoke(mensagens).content
