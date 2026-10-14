# -*- coding: utf-8 -*-
"""Ligação «Dados públicos» (conector ``sky-world``) — fontes do sistema.

Desenho: ``design-fontes-do-sistema.md`` (aprovado a 13/10/2026), §3.1–3.2.

A ligação vive na base do cliente com ``connector_id = 'sky-world'`` e
``sistema = true``. A ``config`` NÃO traz password, só uma referência ao
segredo (``credential_ref``) com o papel Postgres só-leitura desse cliente
(``wt_<slug>``) na base partilhada ``sky_world``::

    {"credential_ref": "sky/production/world/tenants/<slug>",
     "host": "...", "port": 5432, "database": "sky_world", "schema": "mundo"}

A fronteira comercial (o que o cliente activou) está no Postgres — GRANT/REVOKE
de ``wsrc_<fonte>`` ao papel do cliente. Aqui só se lê; o que o papel não pode
ler, a base recusa.

Duas coisas que esta fonte faz e uma ligação Postgres normal não faz:

1. **Resolve a credencial pela referência**, com três guardas: o prefixo é
   exactamente ``sky/<ambiente>/world/tenants/<slug>``, o ``<slug>`` é o do
   cliente DESTE pedido (não se lê o segredo de outro cliente copiando a
   referência), e o valor fica em cache 5 min (a rotação apanha-se sozinha).
2. **Diz de onde vêm os dados e de quando** (:meth:`atribuicao`): fonte,
   licença/atribuição e a hora do dado, lidos de ``mundo.fontes`` (o backend
   concede-a com cada fonte; ``mundo.fontes_visiveis`` do desenho fica de
   reserva). A regra da licença obriga a citar a fonte e a hora sempre que
   uma tabela destas entra numa resposta.

O formato da ``config`` e do segredo (``{"username", "password"}``), o modo
``local`` e o ``WORLD_TENANT_SECRET_PREFIX`` seguem o backend
(``docs/contrato-fontes-do-sistema.md``, ``fontes_sistema/credenciais.py``).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus

from core.data_sources.base import SQLAlchemyDataSource
from core.dialects import Dialect
from core.logging_utils import log_event

CONECTOR_SKY_WORLD = "sky-world"
CONECTORES_SKY_WORLD = {"sky-world", "sky_world", "skyworld"}

ESQUEMA_OMISSAO = "mundo"

# ``sky/<ambiente>/world/tenants/<slug>`` — slug com a regra do registo de
# clientes (^[a-z][a-z0-9-]{1,48}$).
_RE_REF = re.compile(r"^sky/([a-z0-9-]{2,32})/world/tenants/([a-z][a-z0-9-]{1,48})$")

# Tabela de ``mundo`` → nome da fonte em ``mundo.fontes`` (o carregador do
# sky-backend, ``scripts/dados_publicos/mundo/carregar.py::CATALOGO``). Quando
# o catálogo da plataforma passar a gravar ``tabelas`` na própria vista, a
# coluna ganha a esta lista.
TABELA_PARA_FONTE: Dict[str, str] = {
    "gasolineras_precio": "gasolineras",
    "gasolineras_rota": "gasolineras",
    "gasoleo_historico_diario": "gasoleo_historico",
    "gasoleo_ue_semanal": "gasoleo_ue",
    "incidencias_trafico": "incidencias",
    "festivos": "festivos",
    "cambio_eur": "cambio",
    "tempo_cidades": "tempo",
    "portagens": "portagens",
    "restricoes_pesados": "restricoes",
    "rotas_referencia": "rotas",
}

# Cadência esperada (minutos) por fonte. ``atrasada`` = o dado tem mais de
# 2 × a cadência (desenho §2.1, ``cadencia_min``).
CADENCIA_MIN: Dict[str, int] = {
    "gasolineras": 30,
    "incidencias": 5,
    "gasoleo_historico": 24 * 60,
    "cambio": 24 * 60,
    "tempo": 6 * 60,
    "gasoleo_ue": 7 * 24 * 60,
    "festivos": 31 * 24 * 60,
    "rotas": 31 * 24 * 60,
    "portagens": 366 * 24 * 60,
    "restricoes": 366 * 24 * 60,
}

_TTL_SEGREDO_S = 300
_TTL_ATRIBUICAO_S = 60


class CredencialRecusada(ValueError):
    """A referência ao segredo não pertence a este cliente (ou é inválida)."""


# ── segredo por referência ────────────────────────────────────────────────

_cache_segredos: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def _ler_segredo_aws(ref: str) -> Dict[str, Any]:  # pragma: no cover - rede
    import boto3  # lazy: testes e dev local nunca chegam cá

    blob = boto3.client("secretsmanager").get_secret_value(SecretId=ref)["SecretString"]
    return json.loads(blob)


# Ponto de injecção para os testes (e para um cofre diferente amanhã).
ler_segredo = _ler_segredo_aws


_RE_SLUG = re.compile(r"^[a-z][a-z0-9-]{1,48}$")


def validar_credential_ref(ref: str, slug_do_pedido: Optional[str]) -> str:
    """Devolve o slug da referência, ou rebenta.

    ``slug_do_pedido`` = o cliente resolvido para ESTE pedido. ``None`` só em
    modo de cliente único (dev local, ``MULTI_TENANT_ENABLED`` desligado).

    Com ``WORLD_TENANT_SECRET_PREFIX`` definido (o mesmo valor do backend,
    ex. ``sky/production/world/tenants/``) a referência tem de ser
    EXACTAMENTE ``<prefixo><slug>``; sem ele, aceita-se o formato
    ``sky/<ambiente>/world/tenants/<slug>``.
    """
    ref = (ref or "").strip()
    prefixo = (os.environ.get("WORLD_TENANT_SECRET_PREFIX") or "").strip()
    if prefixo:
        slug_ref = ref[len(prefixo) :] if ref.startswith(prefixo) else ""
        if not _RE_SLUG.match(slug_ref):
            raise CredencialRecusada(
                f"credential_ref inválida: esperado {prefixo}<slug>"
            )
    else:
        m = _RE_REF.match(ref)
        if not m:
            raise CredencialRecusada(
                "credential_ref inválida: esperado sky/<ambiente>/world/tenants/<slug>"
            )
        slug_ref = m.group(2)
    if slug_do_pedido is not None and slug_ref != slug_do_pedido:
        raise CredencialRecusada(
            f"credential_ref de outro cliente ({slug_ref!r}) num pedido de {slug_do_pedido!r}"
        )
    return slug_ref


def _credencial_local(slug: str) -> Dict[str, Any]:
    """Modo ``local`` do backend (``WORLD_CREDENTIAL_BACKEND=local``).

    O backend não guarda segredo nenhum em dev/testes: a password do papel
    ``wt_<slug>`` é derivada do ``ENCRYPTION_KEY`` por HMAC
    (``sky-backend src/services/fontes_sistema/credenciais.py``). O sky-ai
    partilha o ``ENCRYPTION_KEY`` (decifra as configs), por isso deriva a
    mesma. Recusado com ``ENVIRONMENT=production``.
    """
    import base64
    import hashlib
    import hmac

    if (os.environ.get("ENVIRONMENT") or "").lower() == "production":
        raise CredencialRecusada(
            "WORLD_CREDENTIAL_BACKEND=local não é permitido em produção"
        )
    chave = (
        os.environ.get("ENCRYPTION_KEY") or os.environ.get("JWT_SECRET_KEY") or ""
    ).encode()
    if not chave:
        raise CredencialRecusada("modo local sem ENCRYPTION_KEY")
    mac = hmac.new(chave, f"sky_world:{slug}".encode(), hashlib.sha256).digest()
    return {
        "username": "wt_" + slug.replace("-", "_"),
        "password": base64.urlsafe_b64encode(mac).decode().rstrip("="),
    }


def _slug_do_pedido() -> Optional[str]:
    """O cliente deste pedido; ``None`` em modo de cliente único.

    Com multi-cliente ligado e sem cliente resolvido (contexto por omissão),
    recusa-se: é exactamente o caso em que um trabalho fora de um pedido
    acabaria a ler o segredo «de alguém».
    """
    try:
        from core.tenant_context import current_tenant, multi_tenant_enabled
    except Exception:  # pragma: no cover
        return None
    if not multi_tenant_enabled():
        return None
    ctx = current_tenant()
    if ctx.is_default:
        raise CredencialRecusada(
            "ligação sky-world sem cliente resolvido (falta X-Tenant-Slug)"
        )
    return ctx.slug


def resolver_credencial(ref: str, slug_do_pedido: Optional[str]) -> Dict[str, Any]:
    slug_ref = validar_credential_ref(ref, slug_do_pedido)
    if (os.environ.get("WORLD_CREDENTIAL_BACKEND") or "aws").strip().lower() == "local":
        return _credencial_local(slug_ref)
    agora = time.monotonic()
    with _cache_lock:
        hit = _cache_segredos.get(ref)
        if hit and agora - hit[0] < _TTL_SEGREDO_S:
            return hit[1]
    valor = ler_segredo(ref)
    if not isinstance(valor, dict):
        raise CredencialRecusada("segredo sky-world sem formato JSON de objecto")
    with _cache_lock:
        _cache_segredos[ref] = (agora, valor)
    return valor


def limpar_cache_segredos() -> None:
    with _cache_lock:
        _cache_segredos.clear()


def _credenciais(segredo: Dict[str, Any]) -> Tuple[str, str]:
    user = segredo.get("username") or segredo.get("user")
    pwd = segredo.get("password")
    if user and pwd is not None:
        return str(user), str(pwd)
    url = segredo.get("url")
    if url:
        from urllib.parse import unquote, urlparse

        p = urlparse(url)
        if p.username and p.password is not None:
            return unquote(p.username), unquote(p.password)
    raise CredencialRecusada("segredo sky-world sem username/password")


def dsn_da_config(cfg: Dict[str, Any], slug_do_pedido: Optional[str] = None) -> str:
    """Monta o DSN de uma ligação sky-world.

    A ``config`` nunca deve trazer password (desenho §3.2), mas aceita-se
    ``username``/``password`` em claro para o dev local e para a fase 0
    (ligação criada à mão). Com ``credential_ref`` a password vem SEMPRE do
    segredo — uma password na config é ignorada.
    """
    host = cfg.get("host")
    port = cfg.get("port") or 5432
    db = cfg.get("database") or cfg.get("dbname") or "sky_world"
    ref = cfg.get("credential_ref")
    if ref:
        user, pwd = _credenciais(resolver_credencial(ref, slug_do_pedido))
    else:
        user = cfg.get("username") or cfg.get("user")
        pwd = cfg.get("password") or ""
    if cfg.get("dsn") and not ref:
        return str(cfg["dsn"])
    if not (host and user):
        raise ValueError("ligação sky-world precisa de host e de credential_ref")
    dsn = f"postgresql+psycopg2://{quote_plus(str(user))}:{quote_plus(str(pwd))}@{host}:{port}/{db}"
    ssl = cfg.get("ssl_mode") or cfg.get("sslmode")
    if ssl:
        dsn += f"?sslmode={ssl}"
    return dsn


# ── atribuição e frescura ─────────────────────────────────────────────────


@dataclass
class Atribuicao:
    fonte: str
    atribuicao: str
    licenca: str
    dado_de: Optional[datetime]
    estado: str
    atrasada: bool

    def como_dict(self) -> Dict[str, Any]:
        return {
            "fonte": self.fonte,
            "atribuicao": self.atribuicao,
            "licenca": self.licenca,
            "dado_de": self.dado_de.isoformat() if self.dado_de else None,
            "estado": self.estado,
            "atrasada": self.atrasada,
        }


def _como_utc(v: Any) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


def esta_atrasada(
    fonte: str,
    dado_de: Optional[datetime],
    estado: str,
    agora: Optional[datetime] = None,
) -> bool:
    if (estado or "").lower() == "erro":
        return True
    if dado_de is None:
        return False
    cad = CADENCIA_MIN.get(fonte)
    if not cad:
        return False
    agora = agora or datetime.now(timezone.utc)
    return (agora - dado_de).total_seconds() > 2 * cad * 60


def nome_da_tabela(fisico: str) -> str:
    return (fisico or "").replace('"', "").split(".")[-1].strip().lower()


def fontes_das_tabelas(tabelas: Iterable[str]) -> List[str]:
    vistas: List[str] = []
    for t in tabelas or []:
        f = TABELA_PARA_FONTE.get(nome_da_tabela(t))
        if f and f not in vistas:
            vistas.append(f)
    return vistas


def atribuicoes_das_linhas(
    linhas: List[Dict[str, Any]], fontes: List[str], agora: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    """Filtra as linhas de ``mundo.fontes`` às ``fontes`` pedidas, por ordem."""
    por_nome = {str(l.get("nome")): l for l in linhas or []}
    out: List[Dict[str, Any]] = []
    for f in fontes:
        l = por_nome.get(f)
        if not l:
            continue
        dado_de = _como_utc(l.get("dado_de")) or _como_utc(l.get("ultima_actualizacao"))
        estado = str(l.get("estado") or "ok")
        out.append(
            Atribuicao(
                fonte=f,
                atribuicao=str(l.get("atribuicao") or l.get("descricao") or f),
                licenca=str(l.get("licenca") or ""),
                dado_de=dado_de,
                estado=estado,
                atrasada=esta_atrasada(f, dado_de, estado, agora),
            ).como_dict()
        )
    return out


class SkyWorldDataSource(SQLAlchemyDataSource):
    """Postgres só-leitura em ``sky_world`` com atribuição das fontes."""

    sistema = True
    connector_id = CONECTOR_SKY_WORLD

    def __init__(
        self, engine, label: str = "sky-world", esquema: str = ESQUEMA_OMISSAO
    ):
        super().__init__(engine=engine, dialect=Dialect.POSTGRES, label=label)
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", esquema or ""):
            raise ValueError(f"esquema inválido para sky-world: {esquema!r}")
        self.esquema = esquema
        self._cache_fontes: Tuple[float, List[Dict[str, Any]]] = (0.0, [])

    def _linhas_fontes(self) -> List[Dict[str, Any]]:
        agora = time.monotonic()
        ts, linhas = self._cache_fontes
        if linhas and agora - ts < _TTL_ATRIBUICAO_S:
            return linhas
        colunas = (
            "nome, descricao, licenca, atribuicao, dado_de, ultima_actualizacao, estado"
        )
        # ``fontes`` é concedida com cada ``wsrc_*`` (backend, fontes_sistema/
        # mundo.py); a vista ``fontes_visiveis`` do desenho fica de reserva.
        for rel in ("fontes", "fontes_visiveis"):
            try:
                linhas = self.run_query(f"SELECT {colunas} FROM {self.esquema}.{rel}")
                self._cache_fontes = (agora, linhas)
                return linhas
            except Exception as exc:  # vista ainda não criada → tabela
                log_event(
                    "sky_world_fontes_indisponivel",
                    {"relacao": rel, "error": str(exc)[:200]},
                )
        return []

    def atribuicao(self, tabelas: Iterable[str]) -> List[Dict[str, Any]]:
        """Fonte, licença e hora do dado das tabelas usadas numa resposta."""
        fontes = fontes_das_tabelas(tabelas)
        if not fontes:
            return []
        try:
            return atribuicoes_das_linhas(self._linhas_fontes(), fontes)
        except Exception as exc:  # nunca partir uma resposta por isto
            log_event("sky_world_atribuicao_falhou", {"error": str(exc)[:300]})
            return []


def construir(conn_id: str, cfg: Dict[str, Any]) -> SkyWorldDataSource:
    """Usado pela ``DataSourceFactory`` para ``connector_id = 'sky-world'``."""
    from sqlalchemy import create_engine

    esquema = cfg.get("schema") or ESQUEMA_OMISSAO
    dsn = dsn_da_config(cfg, _slug_do_pedido() if cfg.get("credential_ref") else None)
    engine = create_engine(
        dsn,
        future=True,
        pool_pre_ping=True,
        # O papel do cliente já tem default_transaction_read_only e
        # statement_timeout no Postgres; repetir aqui é a segunda barreira.
        connect_args=(
            {"options": f"-c default_transaction_read_only=on -c search_path={esquema}"}
            if dsn.startswith("postgresql")
            else {}
        ),
    )
    log_event(
        "build_sky_world_datasource",
        {
            "connection_id": conn_id,
            "schema": esquema,
            "por_referencia": bool(cfg.get("credential_ref")),
        },
    )
    return SkyWorldDataSource(
        engine=engine, label=f"sky-world:{conn_id}", esquema=esquema
    )


def e_fonte_do_sistema(ds: Any) -> bool:
    return bool(getattr(ds, "sistema", False)) and hasattr(ds, "atribuicao")
