# core/llm/providers.py
from __future__ import annotations

from typing import Protocol, List, Dict, Any

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
