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
    Provider para modelos locais via Ollama.
    Converte mensagens de chat em prompt único para SLMs.
    """
    
    def __init__(
        self, 
        model: str, 
        base_url: str = "http://localhost:11434",
        temperature: float = 0.0,
        num_ctx: int = 4096  # Contexto grande para schemas
    ):
        from langchain_community.llms import Ollama
        
        self.model_name = model
        self.llm = Ollama(
            base_url=base_url,
            model=model,
            temperature=temperature,
            num_ctx=num_ctx
        )
    
    def invoke(self, messages: List[Dict[str, str]]) -> Any:
        """
        Converte lista de mensagens em prompt único.
        
        Formato esperado pelo Ollama:
        ### SYSTEM
        <system content>
        
        ### USER
        <user content>
        """
        prompt_parts = []
        
        for msg in messages:
            role = msg.get("role", "user").upper()
            content = msg.get("content", "")
            prompt_parts.append(f"### {role}\\n{content}\\n")
        
        full_prompt = "\\n".join(prompt_parts)
        try:
            response_text = self.llm.invoke(full_prompt)
            
            # Criar objeto compatível com LangChain (Output wrapper)
            class ResponseWrapper:
                def __init__(self, content):
                    self.content = content
            
            log_event(
                "ollama_invoke_success",
                {
                    "model": self.model_name,
                    "prompt_length": len(full_prompt),
                },
            )
            return ResponseWrapper(content=response_text)
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
        """
        Stream tokens from Ollama response.
        Yields string chunks as they are generated.
        """
        prompt_parts = []
        for msg in messages:
            role = msg.get("role", "user").upper()
            content = msg.get("content", "")
            prompt_parts.append(f"### {role}\\n{content}\\n")
        
        full_prompt = "\\n".join(prompt_parts)
        
        try:
            for chunk in self.llm.stream(full_prompt):
                if chunk:
                    yield chunk
            
            log_event(
                "ollama_stream_success",
                {
                    "model": self.model_name,
                    "prompt_length": len(full_prompt),
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
