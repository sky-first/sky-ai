# core/llm/providers.py
from __future__ import annotations

import contextvars
import os

from typing import Protocol, List, Dict, Any, AsyncIterator, Iterator

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from core.logging_utils import log_event
from core.llm.conteudo import texto_do_conteudo


def _com_conteudo_em_texto(resposta: Any) -> Any:
    """Cumpre o contrato do fornecedor: ``.content`` é ``str``.

    A Converse devolve uma lista de blocos quando a resposta traz raciocínio
    ou mais de um bloco. Fica só o texto; o resto da mensagem
    (``usage_metadata``, ``response_metadata``, ``tool_calls``) mantém-se.
    """
    conteudo = getattr(resposta, "content", None)
    if conteudo is None or isinstance(conteudo, str):
        return resposta
    texto = texto_do_conteudo(conteudo)
    try:
        return resposta.model_copy(update={"content": texto})
    except Exception:  # noqa: BLE001 — objecto sem pydantic
        try:
            resposta.content = texto
        except Exception:  # noqa: BLE001
            pass
        return resposta


class LLMProvider(Protocol):
    """
    Interface mínima que o resto do código espera.
    Qualquer implementação deve aceitar uma lista de mensagens
    no formato [{'role': 'system'|'user'|'assistant', 'content': '...'}]
    e retornar um objeto com atributo .content (string).
    """

    def invoke(self, messages: List[Dict[str, str]]) -> Any: ...

    def stream(self, messages: List[Dict[str, str]]) -> Iterator[str]:
        """
        Stream tokens from LLM response.
        Returns an iterator of string chunks.
        """
        ...


#: Quanto tempo se espera por uma resposta do modelo antes de desistir.
#:
#: Uma pergunta que demora mais de dois minutos ja falhou do ponto de vista
#: de quem espera — e o limite do cliente que a app usa. O que se ganha aqui
#: nao e velocidade: e a diferenca entre um erro legivel e uma app parada.
#:
#: Medido: a 28/09 uma pergunta real demorou 76 s e passou; a 29/09 outra
#: passou dos 120 s e o cliente desistiu sem nunca receber nada.
_LIMITE_DE_ESPERA = float(os.getenv("LLM_TIMEOUT_SECONDS", "90"))


#: Rota e papel da chamada em curso — postos pelo ``LLMDoCaminhoMultiFonte``
#: (core/llm/fornecedor_multi_fonte.py) à volta de cada chamada do caminho
#: multi-fonte. Fora dele: rota «global», papel desconhecido. Um contextvar
#: (e não um atributo) porque as fatias correm em threads: cada chamada
#: põe-no e lê-o na sua própria thread.
_ROTA_DA_CHAMADA: "contextvars.ContextVar[tuple]" = contextvars.ContextVar(
    "rota_da_chamada_llm", default=("global", None)
)


def tokens_da_resposta(resposta: Any) -> Dict[str, Any]:
    """``{input_tokens, output_tokens}`` de uma resposta LangChain (ou {})."""
    um = getattr(resposta, "usage_metadata", None) or {}
    if not um:
        meta = getattr(resposta, "response_metadata", None) or {}
        tu = meta.get("token_usage") or meta.get("usage") or {}
        um = {
            "input_tokens": tu.get("prompt_tokens") or tu.get("inputTokens"),
            "output_tokens": tu.get("completion_tokens") or tu.get("outputTokens"),
        }
    out = {}
    for k in ("input_tokens", "output_tokens"):
        v = um.get(k) if isinstance(um, dict) else None
        if isinstance(v, int):
            out[k] = v
    return out


class _Cronometro:
    """Mede UMA chamada ao modelo e escreve ``llm_call_timing``.

    12/10/2026: dos 82,6 s de «Lista las 5 gasolineras…» só a chamada do
    especialista dizia quanto tinha demorado. Toda a chamada a um fornecedor
    passa por aqui — invoke e stream, sucesso e erro — com o modelo, quem a
    fez (módulo.função), o tamanho do prompt e o tempo.

    14/10/2026 (opção B): também o ``provider`` (bedrock/openai/ollama), a
    ``rota`` (global ou multi_fonte), o ``papel`` no caminho multi-fonte e os
    tokens de entrada/saída quando a resposta os traz — para se saber o
    custo real de cada caminho a partir dos registos.
    """

    def __init__(
        self,
        model: str,
        messages: Any,
        modo: str = "invoke",
        provider: str | None = None,
    ) -> None:
        self.model = model
        self.modo = modo
        self.provider = provider
        self.rota, self.papel = _ROTA_DA_CHAMADA.get()
        self.tokens: Dict[str, Any] = {}
        try:
            self.prompt_chars = sum(
                len(str(m.get("content") or "")) if isinstance(m, dict) else len(str(m))
                for m in (messages or [])
            )
        except Exception:
            self.prompt_chars = None
        try:
            from latency_timing import quem_chamou

            self.caller = quem_chamou()
        except Exception:
            self.caller = "?"
        self.ok = False
        self._t0 = 0.0

    def contar(self, resposta: Any) -> None:
        """Guarda os tokens da resposta (invoke) ou do último pedaço (stream)."""
        try:
            t = tokens_da_resposta(resposta)
            if t:
                self.tokens = t
        except Exception:
            pass

    def __enter__(self) -> "_Cronometro":
        import time

        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, *exc) -> bool:
        import time

        ms = (time.perf_counter() - self._t0) * 1000
        try:
            from latency_timing import registar_tempo

            campos: Dict[str, Any] = dict(
                model=self.model,
                provider=self.provider,
                rota=self.rota,
                caller=self.caller,
                mode=self.modo,
                prompt_chars=self.prompt_chars,
                ok=exc_type is None,
            )
            if self.papel:
                campos["papel"] = self.papel
            campos.update(self.tokens)
            registar_tempo(
                "llm_call_timing",
                ms,
                detalhe=f"llm:{self.caller}",
                **campos,
            )
        except Exception:
            pass
        return False


class LangChainChatOpenAIProvider:
    """
    Implementação concreta usando langchain-openai ChatOpenAI.
    Permite plugar gpt-4o, gpt-4o-mini etc. de forma agnóstica.
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> None:
        self._chat = ChatOpenAI(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            # ⚠️ **Sem isto, uma paragem do fornecedor pendurava o pedido.**
            #
            # A 29/09 o smoke test de producao estourou aos 120 s numa
            # pergunta, e o pod nao escreveu UMA linha durante esse tempo: o
            # `context_bundle_built` as 14:37:15 e depois silencio ate
            # 14:39:15. No dia anterior, uma pergunta real da app demorou
            # 76,171 s. Quem esperava nao via erro nenhum — via uma app
            # parada, e lia isso como avaria do backend.
            #
            # O `ChatOpenAI` sem `timeout` herda o valor por omissao do SDK
            # (600 s) e ainda repete duas vezes: meia hora de silencio no
            # pior caso. O provedor do Ollama, mesmo ao lado, ja tinha 300 s.
            #
            # Isto NAO torna o modelo mais rapido — torna a lentidao
            # visivel, que e o que falta hoje.
            timeout=_LIMITE_DE_ESPERA,
            max_retries=1,
        )

    def _convert_messages(self, messages: List[Dict[str, str]]):
        """
        Converte [{'role': 'system', 'content': '...'}, ...]
        para a lista de mensagens do LangChain (SystemMessage, HumanMessage, etc.).
        """
        lc_msgs = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")

            if role == "system":
                lc_msgs.append(SystemMessage(content=content))
            elif role == "assistant":
                lc_msgs.append(AIMessage(content=content))
            else:
                # "user" ou qualquer outro cai aqui
                lc_msgs.append(HumanMessage(content=content))
        return lc_msgs

    def invoke(self, messages: List[Dict[str, str]]):
        lc_msgs = self._convert_messages(messages)
        try:
            from latency_timing import timed_span

            with timed_span("llm_call", node="openai"), _Cronometro(
                getattr(self._chat, "model_name", "unknown"),
                messages,
                provider="openai",
            ) as cron:
                resp = self._chat.invoke(lc_msgs)
                cron.contar(resp)
            log_event(
                "llm_invoke_success",
                {
                    "model": getattr(self._chat, "model_name", "unknown"),
                    "num_messages": len(messages),
                },
            )
            return resp
        except Exception as e:
            log_event(
                "llm_invoke_error",
                {
                    "model": getattr(self._chat, "model_name", "unknown"),
                    "num_messages": len(messages),
                    "error": str(e)[:500],
                },
            )
            raise

    def stream(self, messages: List[Dict[str, str]]) -> Iterator[str]:
        """
        Stream tokens from LLM response.
        Yields string chunks as they are generated.
        """
        lc_msgs = self._convert_messages(messages)
        try:
            with _Cronometro(
                getattr(self._chat, "model_name", "unknown"),
                messages,
                "stream",
                provider="openai",
            ) as cron:
                for chunk in self._chat.stream(lc_msgs):
                    cron.contar(chunk)
                    if hasattr(chunk, "content") and chunk.content:
                        yield chunk.content
            log_event(
                "llm_stream_success",
                {
                    "model": getattr(self._chat, "model_name", "unknown"),
                    "num_messages": len(messages),
                },
            )
        except Exception as e:
            log_event(
                "llm_stream_error",
                {
                    "model": getattr(self._chat, "model_name", "unknown"),
                    "num_messages": len(messages),
                    "error": str(e)[:500],
                },
            )
            raise


# ── Bedrock: 10 pedidos/min e o «Too many requests» ─────────────────────
#
# 14/10/2026: as quotas do Claude na conta de produção ficaram em 5–6 M
# tokens/min mas SÓ 10 pedidos/min por modelo. Uma pergunta faz 3 a 6
# chamadas (orquestrador, especialista por fatia, merger, formatador): à
# segunda pergunta seguida a Converse responde ``ThrottlingException`` e a
# pergunta morria. Espera-se e tenta-se outra vez — SÓ nesse erro. Um
# ValidationException, um AccessDenied ou um modelo inexistente sobem logo,
# como antes.

#: Códigos de erro da Bedrock que querem dizer «espera e repete».
#: 14/10/2026 (portão da opção B): o Haiku pelo perfil eu.* respondeu
#: ``ServiceUnavailableException`` («Bedrock is unable to process your
#: request») depois das 4 repetições rápidas do botocore. É transitório e a
#: Bedrock manda repetir — com a mesma espera crescente do limite.
_CODIGOS_DE_LIMITE = {
    "ThrottlingException",
    "TooManyRequestsException",
    "ServiceUnavailableException",
}

#: Quantas vezes se repete depois da primeira tentativa.
_LIMITE_REPETICOES = int(os.getenv("BEDROCK_THROTTLE_MAX_RETRIES", "5"))
#: Primeira espera (s); dobra a cada repetição até ao tecto.
_ESPERA_INICIAL = float(os.getenv("BEDROCK_THROTTLE_BASE_SECONDS", "2"))
_ESPERA_MAXIMA = float(os.getenv("BEDROCK_THROTTLE_MAX_SECONDS", "20"))


def _dormir(segundos: float) -> None:  # substituível nos testes
    import time

    time.sleep(segundos)


def e_limite_da_bedrock(erro: BaseException) -> bool:
    """O erro é a Bedrock a dizer «demasiados pedidos»?"""
    resposta = getattr(erro, "response", None)
    if isinstance(resposta, dict):
        codigo = (resposta.get("Error") or {}).get("Code")
        if codigo in _CODIGOS_DE_LIMITE:
            return True
    return type(erro).__name__ in _CODIGOS_DE_LIMITE


def _espera(tentativa: int) -> float:
    import random

    teto = min(_ESPERA_MAXIMA, _ESPERA_INICIAL * (2**tentativa))
    # «full jitter» limitado a metade: pedidos paralelos (fatias) não
    # acordam todos no mesmo segundo.
    return teto * random.uniform(0.5, 1.0)


def _registar_repeticao(modelo: str, tentativa: int, espera: float, erro) -> None:
    log_event(
        "bedrock_throttled_retry",
        {
            "model": modelo,
            "attempt": tentativa + 1,
            "max_retries": _LIMITE_REPETICOES,
            "wait_seconds": round(espera, 2),
            "error": str(erro)[:200],
        },
    )


_CLASSE_CONVERSE = None


def _converse_com_repeticao():
    """``ChatBedrockConverse`` que repete no limite de pedidos.

    É uma subclasse (e não um ``.with_retry``) para manter ``bind_tools``: o
    orquestrador ReAct e o full-context agent falam com o ``_chat``
    directamente, por isso a repetição tem de viver no próprio modelo.
    """
    global _CLASSE_CONVERSE
    import langchain_aws  # type: ignore

    ChatBedrockConverse = langchain_aws.ChatBedrockConverse
    # A cache é por classe-base: quem substitui ``langchain_aws.ChatBedrockConverse``
    # (os testes, sem AWS) recebe uma subclasse da substituta.
    if _CLASSE_CONVERSE is not None and _CLASSE_CONVERSE[0] is ChatBedrockConverse:
        return _CLASSE_CONVERSE[1]

    class ChatBedrockConverseComRepeticao(ChatBedrockConverse):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            tentativa = 0
            while True:
                try:
                    return super()._generate(
                        messages, stop=stop, run_manager=run_manager, **kwargs
                    )
                except Exception as e:  # noqa: BLE001
                    if not e_limite_da_bedrock(e) or tentativa >= _LIMITE_REPETICOES:
                        raise
                    espera = _espera(tentativa)
                    _registar_repeticao(self.model_id, tentativa, espera, e)
                    _dormir(espera)
                    tentativa += 1

        def _stream(self, messages, stop=None, run_manager=None, **kwargs):
            tentativa = 0
            while True:
                emitiu = False
                try:
                    for pedaco in super()._stream(
                        messages, stop=stop, run_manager=run_manager, **kwargs
                    ):
                        emitiu = True
                        yield pedaco
                    return
                except Exception as e:  # noqa: BLE001
                    # Depois do primeiro pedaço já não se repete: quem lê
                    # receberia o início da resposta duas vezes.
                    if (
                        emitiu
                        or not e_limite_da_bedrock(e)
                        or tentativa >= _LIMITE_REPETICOES
                    ):
                        raise
                    espera = _espera(tentativa)
                    _registar_repeticao(self.model_id, tentativa, espera, e)
                    _dormir(espera)
                    tentativa += 1

    _CLASSE_CONVERSE = (ChatBedrockConverse, ChatBedrockConverseComRepeticao)
    return ChatBedrockConverseComRepeticao


class BedrockChatProvider:
    """
    Provider for Anthropic Claude on AWS Bedrock.

    Authentication is via IRSA when running on EKS — boto3 transparently
    picks up the OIDC token mounted at
    /var/run/secrets/eks.amazonaws.com/serviceaccount/token and exchanges
    it for the role `sky-eks-staging-bedrock` (Terraform: infra/aws/
    _eks_staging/irsa.tf). No long-lived AWS keys ever land in the env.

    Projeto A (Model B) — when ``inference_profile_arn`` is supplied the
    provider routes through that profile instead of the bare model id.
    Bedrock Application Inference Profiles tag every invocation with the
    profile's ARN, which lets us split spend per tenant in Cost Explorer
    without any extra plumbing. The lookup happens once at provider
    construction; callers that want per-request routing build a fresh
    provider per request.
    """

    def __init__(
        self,
        model: str,
        region: str = "eu-west-1",
        temperature: float = 0.0,
        max_tokens: int | None = None,
        inference_profile_arn: str | None = None,
    ) -> None:
        # Bedrock's ``model`` parameter accepts either a model id
        # (``eu.anthropic.claude-…``) or any inference-profile ARN.
        # When the caller hands us an ARN we use it verbatim and keep
        # the original model id around for logging.
        self.model_name = inference_profile_arn or model
        self.base_model_id = model
        self.inference_profile_arn = inference_profile_arn

        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "region_name": region,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        self._chat = _converse_com_repeticao()(**kwargs)
        log_event(
            "bedrock_provider_init",
            {
                "model": self.base_model_id,
                "inference_profile_arn": (
                    self.inference_profile_arn[:80] + "…"
                    if self.inference_profile_arn
                    and len(self.inference_profile_arn) > 80
                    else self.inference_profile_arn
                ),
                "region": region,
            },
        )

    def _convert_messages(self, messages: List[Dict[str, str]]):
        lc_msgs = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                lc_msgs.append(SystemMessage(content=content))
            elif role == "assistant":
                lc_msgs.append(AIMessage(content=content))
            else:
                lc_msgs.append(HumanMessage(content=content))
        return lc_msgs

    def invoke(self, messages: List[Dict[str, str]]) -> Any:
        lc_msgs = self._convert_messages(messages)
        try:
            from latency_timing import timed_span

            with timed_span("llm_call", node="bedrock"), _Cronometro(
                self.base_model_id, messages, provider="bedrock"
            ) as cron:
                resp = self._chat.invoke(lc_msgs)
                cron.contar(resp)
            log_event(
                "bedrock_invoke_success",
                {"model": self.model_name, "num_messages": len(messages)},
            )
            return _com_conteudo_em_texto(resp)
        except Exception as e:
            log_event(
                "bedrock_invoke_error",
                {
                    "model": self.model_name,
                    "num_messages": len(messages),
                    "error": str(e)[:500],
                },
            )
            raise

    def stream(self, messages: List[Dict[str, str]]) -> Iterator[str]:
        lc_msgs = self._convert_messages(messages)
        try:
            with _Cronometro(
                self.base_model_id, messages, "stream", provider="bedrock"
            ) as cron:
                for chunk in self._chat.stream(lc_msgs):
                    cron.contar(chunk)
                    if hasattr(chunk, "content") and chunk.content:
                        # ChatBedrockConverse may emit content as a list of
                        # content blocks (text + tool calls). Normalise to a
                        # plain string so the contract matches the other
                        # providers.
                        texto = texto_do_conteudo(chunk.content)
                        if texto:
                            yield texto
            log_event(
                "bedrock_stream_success",
                {"model": self.model_name, "num_messages": len(messages)},
            )
        except Exception as e:
            log_event(
                "bedrock_stream_error",
                {"model": self.model_name, "error": str(e)[:500]},
            )
            raise


class OllamaProvider:
    """
    Provider para modelos locais via Ollama (usando langchain-ollama).
    """

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        temperature: float = 0.0,
        num_ctx: int = 4096,
    ):
        try:
            from langchain_ollama import ChatOllama
        except ImportError:
            # Fallback seguro caso a lib não esteja instalada (evita crash imediato)
            from langchain_community.chat_models import ChatOllama

        self.model_name = model
        self._chat = ChatOllama(
            base_url=base_url,
            model=model,
            temperature=temperature,
            num_ctx=num_ctx,
            # Timeout alto para cold start (RunPod pode demorar)
            timeout=300,
        )

    def _convert_messages(self, messages: List[Dict[str, str]]):
        """
        Converte dicts para SystemMessage, HumanMessage, AIMessage.
        """
        lc_msgs = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")

            if role == "system":
                lc_msgs.append(SystemMessage(content=content))
            elif role == "assistant":
                lc_msgs.append(AIMessage(content=content))
            else:
                lc_msgs.append(HumanMessage(content=content))
        return lc_msgs

    def invoke(self, messages: List[Dict[str, str]]) -> Any:
        # Import cache here to avoid circular dependency
        from core.llm.cache import get_inference_cache, hash_prompt

        # Check cache first
        cache = get_inference_cache()
        # Hash baseado na string crua das mensagens para consistência
        prompt_hash = hash_prompt(messages, self.model_name, 0.0)
        cached_response = cache.get(prompt_hash)

        if cached_response is not None:
            log_event(
                "ollama_cache_hit",
                {"model": self.model_name, "saved_latency": "cached"},
            )
            return cached_response

        lc_msgs = self._convert_messages(messages)

        # Log start
        is_sql_query = "sqlcoder" in self.model_name
        if is_sql_query:
            log_event(
                "ollama_sql_generation_start",
                {
                    "model": self.model_name,
                    "expected_latency_seconds": "8-12",
                    "num_messages": len(messages),
                },
            )

        try:
            # Invoke ChatOllama directly (it handles prompting)
            from latency_timing import timed_span

            with timed_span("llm_call", node="ollama"), _Cronometro(
                self.model_name, messages, provider="ollama"
            ):
                resp = self._chat.invoke(lc_msgs)

            # Wrapper para manter contrato .content
            class ResponseWrapper:
                def __init__(self, content):
                    self.content = content

            result = ResponseWrapper(content=resp.content)

            # Cache result
            cache.set(prompt_hash, result)

            log_event(
                "ollama_invoke_success",
                {
                    "model": self.model_name,
                    "response_length": len(resp.content),
                    "cached": False,
                },
            )
            return result
        except Exception as e:
            log_event(
                "ollama_invoke_error",
                {
                    "model": self.model_name,
                    "error": str(e)[:500],
                },
            )
            raise

    def stream(self, messages: List[Dict[str, str]]) -> Iterator[str]:
        lc_msgs = self._convert_messages(messages)

        try:
            with _Cronometro(self.model_name, messages, "stream", provider="ollama"):
                for chunk in self._chat.stream(lc_msgs):
                    if chunk.content:
                        yield chunk.content

            log_event(
                "ollama_stream_success",
                {
                    "model": self.model_name,
                },
            )
        except Exception as e:
            log_event(
                "ollama_stream_error",
                {
                    "model": self.model_name,
                    "error": str(e)[:500],
                },
            )
            raise
