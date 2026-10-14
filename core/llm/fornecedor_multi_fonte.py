# -*- coding: utf-8 -*-
"""Fornecedor próprio do caminho multi-fonte (opção B, 14/10/2026).

Porquê: o portão das «Fontes do sistema» (``scripts/portao_fontes``) deu
**0/20** com os modelos globais de produção (bedrock-mantle: gpt-oss-120b +
qwen3-coder-30b) e **20/20** com Claude na Bedrock (Haiku 4.5 no
orquestrador/formatador, Sonnet 4.6 no especialista/merger). O Lucas escolheu
pôr Claude SÓ nesse caminho e deixar o resto do serviço como está.

Quando se aplica: a flag ``MULTI_FONTE_POR_LIGACAO(_TENANTS)`` está activa
para o cliente do pedido **e** o orquestrador escolheu tabelas de 2+
ligações (``is_multi_source``). Aí TODAS as chamadas que se seguem — uma por
fatia, as reparações do especialista, o merger (e a sua correcção) e o
formatador — vão para ``MULTI_FONTE_PROVIDER`` com os modelos
``MULTI_FONTE_MODEL_*``. Perguntas de uma só fonte, e clientes sem a flag,
não mudam.

Quem decide que é multi-fonte é o orquestrador, que corre ANTES de se
saber. Por omissão é o orquestrador global (medido no portão; ver o PR).
Com ``MULTI_FONTE_MODEL_ORCHESTRATOR`` definido, o orquestrador dos clientes
da flag passa também para este fornecedor — em todas as perguntas de dados
desses clientes, porque ainda não se sabe quais vão ser multi-fonte.

Falhas: nunca se cai para o modelo global. O qwen dá respostas erradas
neste caminho — é pior do que dizer que não deu. Cada chamada que falha
fica registada (``FalhaDoModelo``) e o grafo responde com
``MULTI_SOURCE_MODEL_UNAVAILABLE``: honesto, na língua da pessoa.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from core.logging_utils import log_event

#: Fornecedores suportados neste caminho.
FORNECEDORES = ("bedrock",)

#: O que o portão mediu a 20/20 (14/10/2026) — usado quando o
#: ``MULTI_FONTE_MODEL_<PAPEL>`` correspondente está vazio.
MODELOS_POR_OMISSAO: Dict[str, str] = {
    "specialist": "eu.anthropic.claude-sonnet-4-6",
    "merger": "eu.anthropic.claude-sonnet-4-6",
    "formatter": "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
}

PAPEIS = ("orchestrator", "specialist", "merger", "formatter")

#: Códigos de erro da Bedrock/botocore por tipo de falha.
_LIMITE = {"ThrottlingException", "TooManyRequestsException"}
_ACESSO = {
    "AccessDeniedException",
    "UnrecognizedClientException",
    "ExpiredTokenException",
    "ExpiredToken",
    "InvalidSignatureException",
    "UnauthorizedOperation",
    "NoCredentialsError",
}
_SERVIDOR = {
    "InternalServerException",
    "ServiceUnavailableException",
    "ModelNotReadyException",
    "ModelTimeoutException",
    "ModelErrorException",
    "ServiceException",
    "ReadTimeoutError",
    "ConnectTimeoutError",
    "EndpointConnectionError",
}


def _codigo(erro: BaseException) -> Optional[str]:
    resposta = getattr(erro, "response", None)
    if isinstance(resposta, dict):
        c = (resposta.get("Error") or {}).get("Code")
        if c:
            return str(c)
    return None


def _estado_http(erro: BaseException) -> Optional[int]:
    resposta = getattr(erro, "response", None)
    if isinstance(resposta, dict):
        meta = resposta.get("ResponseMetadata") or {}
        s = meta.get("HTTPStatusCode")
        if isinstance(s, int):
            return s
    return None


def classificar_falha(erro: BaseException) -> str:
    """``limite`` | ``acesso`` | ``servidor`` | ``outro``.

    Procura em toda a cadeia (``__cause__``/``__context__``): o LangChain
    embrulha o ``ClientError`` do botocore.
    """
    vistos = 0
    atual: Optional[BaseException] = erro
    while atual is not None and vistos < 6:
        nomes = {type(atual).__name__}
        c = _codigo(atual)
        if c:
            nomes.add(c)
        if nomes & _LIMITE:
            return "limite"
        if nomes & _ACESSO:
            return "acesso"
        if nomes & _SERVIDOR:
            return "servidor"
        s = _estado_http(atual)
        if s is not None:
            if s == 429:
                return "limite"
            if s in (401, 403):
                return "acesso"
            if s >= 500:
                return "servidor"
        texto = str(atual)
        if "Too many requests" in texto or "ThrottlingException" in texto:
            return "limite"
        if "AccessDenied" in texto or "not authorized" in texto:
            return "acesso"
        atual = atual.__cause__ or atual.__context__
        vistos += 1
    return "outro"


def fornecedor_configurado(settings_obj: Any = None) -> Optional[str]:
    """O ``MULTI_FONTE_PROVIDER`` válido, ou None (= comportamento de sempre)."""
    if settings_obj is None:
        from config.settings import settings as settings_obj  # type: ignore
    valor = (getattr(settings_obj, "multi_fonte_provider", None) or "").strip().lower()
    if not valor:
        return None
    if valor not in FORNECEDORES:
        log_event(
            "multi_fonte_provider_desconhecido",
            {"valor": valor, "suportados": list(FORNECEDORES)},
        )
        return None
    return valor


def modelo_do_papel(papel: str, settings_obj: Any = None) -> Optional[str]:
    """Modelo do papel no caminho multi-fonte (None = não se aplica)."""
    if settings_obj is None:
        from config.settings import settings as settings_obj  # type: ignore
    definido = (getattr(settings_obj, f"multi_fonte_model_{papel}", None) or "").strip()
    if definido:
        return definido
    # O orquestrador NÃO tem omissão: sem modelo próprio, decide o global.
    return MODELOS_POR_OMISSAO.get(papel)


class LLMDoCaminhoMultiFonte:
    """Embrulha o fornecedor de um papel do caminho multi-fonte.

    - Marca cada chamada com rota ``multi_fonte`` e o papel (para os
      registos ``llm_call_timing``: fornecedor, modelo, tokens).
    - Regista cada falha em ``falhas`` (partilhada pelos papéis do mesmo
      pedido) e volta a lançá-la — quem chama trata como sempre, e o grafo
      troca a resposta pela mensagem honesta.
    - Expõe ``_chat`` e o resto do fornecedor (o orquestrador ReAct fala
      com o ``_chat`` directamente).
    """

    def __init__(
        self,
        interno: Any,
        papel: str,
        provider: str,
        modelo: str,
        falhas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self._interno = interno
        self.papel = papel
        self.provider = provider
        self.modelo = modelo
        self.falhas: List[Dict[str, Any]] = falhas if falhas is not None else []
        self.model_name = getattr(interno, "model_name", modelo)

    def __getattr__(self, nome: str) -> Any:
        # Só chamado para o que não existe aqui (ex.: ``_chat``).
        return getattr(self._interno, nome)

    def _registar(self, erro: BaseException) -> None:
        falha = {
            "papel": self.papel,
            "provider": self.provider,
            "modelo": self.modelo,
            "tipo": classificar_falha(erro),
            "erro": f"{type(erro).__name__}: {str(erro)[:200]}",
        }
        self.falhas.append(falha)
        log_event("multi_fonte_llm_falhou", falha)

    def invoke(self, messages: List[Dict[str, str]]) -> Any:
        from core.llm.providers import _ROTA_DA_CHAMADA

        marca = _ROTA_DA_CHAMADA.set(("multi_fonte", self.papel))
        try:
            return self._interno.invoke(messages)
        except Exception as e:
            self._registar(e)
            raise
        finally:
            _ROTA_DA_CHAMADA.reset(marca)

    def stream(self, messages: List[Dict[str, str]]) -> Iterator[str]:
        from core.llm.providers import _ROTA_DA_CHAMADA

        marca = _ROTA_DA_CHAMADA.set(("multi_fonte", self.papel))
        try:
            for pedaco in self._interno.stream(messages):
                yield pedaco
        except Exception as e:
            self._registar(e)
            raise
        finally:
            try:
                _ROTA_DA_CHAMADA.reset(marca)
            except ValueError:
                # Gerador retomado noutro contexto: o valor morre com ele.
                pass


def criar_llm(
    papel: str,
    falhas: Optional[List[Dict[str, Any]]] = None,
    temperature: float = 0.0,
) -> Optional[LLMDoCaminhoMultiFonte]:
    """O LLM do papel no caminho multi-fonte, ou None se não se aplica.

    None quando ``MULTI_FONTE_PROVIDER`` não está definido (ou é inválido),
    ou quando o papel é o orquestrador sem ``MULTI_FONTE_MODEL_ORCHESTRATOR``.
    """
    from config.settings import settings

    provider = fornecedor_configurado(settings)
    if provider is None:
        return None
    modelo = modelo_do_papel(papel, settings)
    if not modelo:
        return None
    # Sem o perfil de inferência do cliente (``_tenant_bedrock_profile_arn``):
    # esse perfil está ligado a UM modelo (o do provider global) e trocaria
    # o modelo de cada papel em silêncio. O custo deste caminho lê-se nos
    # registos (``llm_call_timing`` com rota=multi_fonte).
    from core.llm.providers import BedrockChatProvider

    interno = BedrockChatProvider(
        model=modelo,
        region=settings.bedrock_region,
        temperature=temperature,
    )
    return LLMDoCaminhoMultiFonte(interno, papel, provider, modelo, falhas)


def tipo_principal(falhas: List[Dict[str, Any]]) -> str:
    """O tipo que explica a falha (o limite pesa mais: é o que passa)."""
    tipos = [f.get("tipo") for f in falhas or []]
    for t in ("limite", "acesso", "servidor"):
        if t in tipos:
            return t
    return "outro"


def mensagem_modelo_indisponivel(tipo: Optional[str], lang: str) -> str:
    """A resposta honesta quando o modelo deste caminho falhou."""
    from core.i18n.i18n import get_message

    chave = (
        "MULTI_SOURCE_MODEL_DENIED" if tipo == "acesso" else "MULTI_SOURCE_MODEL_BUSY"
    )
    return get_message(chave, lang)
