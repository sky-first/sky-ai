# -*- coding: utf-8 -*-
"""Citação obrigatória das fontes públicas numa resposta.

Regra da licença (desenho «Fontes do sistema», §3.7): sempre que uma tabela da
ligação «Dados públicos» (``sky-world``) entra numa resposta, a resposta diz
**a fonte** e **a hora do dado** — e «atrasado» quando o carregador parou ou a
fonte está em erro. O MITECO, por exemplo, exige não alterar a data de
actualização; a DGT/NAP exige atribuição (CC BY).

Não se pede ao modelo: acrescenta-se de forma determinística, depois da
resposta, nos três caminhos que gravam respostas (``run_formatter``, o stream
e — quando a voz passar a ler isto — a voz). O modelo esquecia-se de regras
destas; a correcção dos números já é feita assim pelo mesmo motivo.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

_ROTULO = {
    "pt": ("Fonte", "Fontes", "actualizado às {h} ({d})", "atrasado"),
    "es": ("Fuente", "Fuentes", "actualizado a las {h} ({d})", "con retraso"),
    "en": ("Source", "Sources", "updated at {h} ({d})", "stale"),
}

# Hora mostrada na hora civil de quem pergunta (a ibérica é a dos clientes de
# hoje). Sem tzdata (Windows sem o pacote), cai para UTC e di-lo.
_FUSO = {"pt": "Europe/Lisbon", "es": "Europe/Madrid", "en": "UTC"}


def _lingua(lang: Optional[str]) -> str:
    l = (lang or "pt").lower()[:2]
    return l if l in _ROTULO else "en"


def _hora_local(dado_de: datetime, lingua: str):
    try:
        from zoneinfo import ZoneInfo

        return dado_de.astimezone(ZoneInfo(_FUSO[lingua])), ""
    except Exception:
        return dado_de.astimezone(timezone.utc), " UTC"


def _como_dt(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def juntar(*listas: Optional[Iterable[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Une atribuições de várias fatias sem repetir a mesma fonte."""
    vistas: Dict[str, Dict[str, Any]] = {}
    for lista in listas:
        for a in lista or []:
            chave = str(a.get("fonte") or a.get("atribuicao"))
            if chave not in vistas:
                vistas[chave] = a
    return list(vistas.values())


def linha_de_citacao(
    fontes: Optional[List[Dict[str, Any]]], lang: Optional[str]
) -> str:
    """«Fonte: … · actualizado às 13:05 (13/10/2026)» — vazio sem fontes."""
    if not fontes:
        return ""
    lingua = _lingua(lang)
    um, varios, actualizado, atrasado = _ROTULO[lingua]
    partes: List[str] = []
    for a in fontes:
        texto = str(a.get("atribuicao") or a.get("fonte") or "").strip()
        # «Fuente: X» / «Fonte: X» já trazem o rótulo — não repetir.
        for prefixo in ("Fuente:", "Fonte:", "Source:"):
            if texto.startswith(prefixo):
                texto = texto[len(prefixo) :].strip()
        # Atribuições longas trazem condições de uso depois do ponto: o
        # utilizador precisa do nome da fonte, não do aviso legal inteiro.
        texto = texto.split(". ")[0].rstrip(".")
        dado_de = _como_dt(a.get("dado_de"))
        if dado_de is not None:
            local, sufixo = _hora_local(dado_de, lingua)
            texto += " · " + actualizado.format(
                h=local.strftime("%H:%M") + sufixo, d=local.strftime("%d/%m/%Y")
            )
        if a.get("atrasada"):
            texto += f" ({atrasado})"
        if texto:
            partes.append(texto)
    if not partes:
        return ""
    return f"{um if len(partes) == 1 else varios}: " + "; ".join(partes)


def acrescentar_citacao(
    resposta: str, fontes: Optional[List[Dict[str, Any]]], lang: Optional[str]
) -> str:
    """Acrescenta a linha de citação à resposta, uma só vez."""
    linha = linha_de_citacao(fontes, lang)
    if not linha or not resposta:
        return resposta
    if linha in resposta:
        return resposta
    return f"{resposta.rstrip()}\n\n{linha}"
