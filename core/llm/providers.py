# core/llm/providers.py
from __future__ import annotations

from typing import Protocol, List, Dict, Any, AsyncIterator, Iterator

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from core.logging_utils import log_event


class LLMProvider(Protocol):
    """
    Interface mínima que o resto do código espera.
    Qualquer implementação deve aceitar uma lista de mensagens
    no formato [{'role': 'system'|'user'|'assistant', 'content': '...'}]
    e retornar um objeto com atributo .content (string).
    """
    def invoke(self, messages: List[Dict[str, str]]) -> Any:
        ...
    
    def stream(self, messages: List[Dict[str, str]]) -> Iterator[str]:
        """
        Stream tokens from LLM response.
        Returns an iterator of string chunks.
        """
        ...


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
            resp = self._chat.invoke(lc_msgs)
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
            for chunk in self._chat.stream(lc_msgs):
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


class OllamaProvider:
    """
    Provider para modelos locais via Ollama (usando langchain-ollama).
    """
    
    def __init__(
        self, 
        model: str, 
        base_url: str = "http://localhost:11434",
        temperature: float = 0.0,
        num_ctx: int = 4096
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
                {
                    "model": self.model_name,
                    "saved_latency": "cached"
                }
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
                    "num_messages": len(messages)
                }
            )
        
        try:
            # Invoke ChatOllama directly (it handles prompting)
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
                    "cached": False
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
