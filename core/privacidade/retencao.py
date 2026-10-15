"""Retenção dos registos de auditoria do sky-ai (RGPD, decisão de 15/10/2026).

A política de privacidade diz que os registos técnicos com dados pessoais se
guardam ``RETENCAO_AUDITORIA_DIAS`` (365) e depois se apagam. No sky-ai são
três tabelas, todas com a coluna ``timestamp``:

- ``query_audit_log`` — quem perguntou (``user_id``), a pergunta, o SQL e os
  primeiros 500 caracteres da resposta;
- ``prompt_security_audit`` — ``user_id`` e o texto do prompt (redigido);
- ``security_alerts`` — ``user_id`` e os detalhes do alerta.

Fica de fora, de propósito, o ``chat_history``: é a conversa, e as conversas
pertencem à organização (mesma regra das mensagens no backend). O
``semantic_cache`` já tem prazo próprio (``core/privacidade/cache_semantico``).

Quem chama é a tarefa diária do backend (``src/workers/rgpd_worker.py``), uma
vez por base, via ``POST /privacidade/retencao``. Idempotente: a segunda
passagem não encontra nada. Com ``a_serio=False`` só conta. O resultado são
contagens — nunca perguntas, SQL ou ids de pessoas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

TABELAS_COM_RETENCAO = ("query_audit_log", "prompt_security_audit", "security_alerts")

#: Abaixo disto é quase de certeza uma variável de ambiente mal escrita
#: (``RETENCAO_AUDITORIA_DIAS=0`` apagava a auditoria toda). Recusa-se.
DIAS_MINIMOS = 30


@dataclass
class Resultado:
    base: str
    dry_run: bool
    dias: int
    contagens: Dict[str, int] = field(default_factory=dict)
    falhas: List[str] = field(default_factory=list)

    def como_dict(self) -> Dict[str, Any]:
        return {
            "base": self.base,
            "dry_run": self.dry_run,
            "dias": self.dias,
            "contagens": dict(self.contagens),
            "falhas": list(self.falhas),
        }


async def _existe(db: Any, tabela: str) -> bool:
    from sqlalchemy import text

    r = await db.execute(text("SELECT to_regclass(:t) IS NOT NULL"), {"t": tabela})
    return bool(r.scalar())


async def aplicar_retencao(
    db: Any,
    base: str,
    *,
    dias: int,
    a_serio: bool,
    agora: Optional[datetime] = None,
) -> Resultado:
    """Apaga, numa base, a auditoria com mais de ``dias`` dias.

    Uma tabela que falhe (sem permissão, por exemplo) fica em ``falhas`` e as
    outras seguem — mas, como no Postgres um erro aborta a transacção, faz-se
    rollback antes de continuar.
    """
    from sqlalchemy import text

    if int(dias) < DIAS_MINIMOS:
        raise ValueError(f"RETENCAO_AUDITORIA_DIAS tem de ser >= {DIAS_MINIMOS}")
    corte = (agora or datetime.now(timezone.utc)) - timedelta(days=int(dias))
    res = Resultado(base=base, dry_run=not a_serio, dias=int(dias))
    sufixo = "apagados" if a_serio else "a_apagar"

    for tabela in TABELAS_COM_RETENCAO:
        try:
            if not await _existe(db, tabela):
                continue
            n = (
                await db.execute(
                    text(f'SELECT count(*) FROM {tabela} WHERE "timestamp" < :corte'),
                    {"corte": corte},
                )
            ).scalar() or 0
            if n and a_serio:
                await db.execute(
                    text(f'DELETE FROM {tabela} WHERE "timestamp" < :corte'),
                    {"corte": corte},
                )
                await db.commit()
            res.contagens[f"{tabela}_{sufixo}"] = int(n)
        except Exception as exc:  # noqa: BLE001 — uma tabela não trava as outras
            res.falhas.append(f"{tabela}:{type(exc).__name__}")
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass
    return res
