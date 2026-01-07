# api/routes/widget_titles.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.llm.providers import LangChainChatOpenAIProvider
from core.logging_utils import log_event
from config.settings import settings

router = APIRouter(prefix="/widgets", tags=["widgets"])


class SuggestTitleRequest(BaseModel):
    """Request para sugerir título de widget."""
    question: str = Field(..., description="Pergunta original do widget")
    data_sample: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Amostra dos dados retornados (máx. 5 linhas)"
    )
    answer: Optional[str] = Field(
        default=None, description="Resposta textual da IA (opcional)"
    )
    current_title: Optional[str] = Field(
        default=None, description="Título atual do widget (pode ser genérico)"
    )
    language: str = Field(
        default="pt", description="Idioma para o título (pt, en, es)"
    )


class SuggestTitleResponse(BaseModel):
    """Response com título sugerido."""
    title: str = Field(..., description="Título sugerido pela IA")


@router.post("/suggest-title", response_model=SuggestTitleResponse)
async def suggest_widget_title(request: SuggestTitleRequest):
    """
    Sugere um título melhor e mais descritivo para um widget baseado nos dados retornados.
    
    Esta função analisa:
    - A pergunta original
    - Os dados retornados (amostra)
    - A resposta textual da IA (se disponível)
    - O título atual (que pode ser genérico)
    
    E gera um título mais específico e informativo.
    """
    try:
        # Criar instância do LLM (usar modelo mais leve para tarefa simples)
        llm = LangChainChatOpenAIProvider(
            model=settings.llm_model_formatter or "gpt-4o-mini",
            temperature=0.3,  # Um pouco mais criativo para títulos
            max_tokens=50,  # Títulos são curtos
        )
        
        # Preparar amostra dos dados como texto
        data_text = ""
        if request.data_sample:
            sample = request.data_sample[:5]  # Limitar a 5 linhas
            if sample:
                data_text = "\nDados retornados (amostra):\n"
                for i, row in enumerate(sample, 1):
                    # Formatar linha de forma legível
                    row_str = ", ".join([f"{k}: {v}" for k, v in row.items()])
                    data_text += f"  Linha {i}: {row_str}\n"
        
        # Construir mensagens para o LLM
        system_msg = {
            "role": "system",
            "content": (
                "Você é um especialista em criar títulos descritivos e concisos para widgets de dashboard.\n"
                "Analise a pergunta, os dados retornados e sugira um título claro e informativo.\n\n"
                "REGRAS IMPORTANTES:\n"
                "- O título deve ser CURTO (máximo 60 caracteres)\n"
                "- Deve descrever claramente o que o widget mostra\n"
                "- Use o idioma especificado pelo usuário\n"
                "- Seja ESPECÍFICO: evite títulos genéricos como 'Widget', 'Chart', 'Dados', 'Gráfico'\n"
                "- Baseie-se nos DADOS REAIS retornados, não apenas na pergunta\n"
                "- Se os dados mostram métricas específicas, mencione-as no título\n"
                "- Se os dados mostram categorias ou dimensões, inclua-as no título\n"
                "- Retorne APENAS o título, sem aspas, sem explicações, sem prefixos\n"
                "- Exemplos de bons títulos:\n"
                "  * 'Vendas por Mês' (não 'Gráfico de Vendas')\n"
                "  * 'Top 10 Clientes' (não 'Widget de Clientes')\n"
                "  * 'Receita Total 2024' (não 'KPI')\n"
                "  * 'Distribuição por Região' (não 'Chart')\n"
            )
        }
        
        user_content = f"Pergunta original: {request.question}\n\n"
        
        if request.current_title:
            user_content += f"Título atual (genérico): {request.current_title}\n\n"
        
        if data_text:
            user_content += data_text + "\n"
        
        if request.answer:
            # Limitar resposta a 200 caracteres para não sobrecarregar
            answer_snippet = request.answer[:200]
            user_content += f"Resposta da IA: {answer_snippet}\n\n"
        
        user_content += (
            f"Idioma desejado: {request.language}\n\n"
            "Sugira um título melhor e mais descritivo para este widget baseado nas informações acima."
        )
        
        user_msg = {
            "role": "user",
            "content": user_content
        }
        
        # Chamar LLM
        resp = llm.invoke([system_msg, user_msg])
        title = getattr(resp, "content", "").strip()
        
        # Limpar título: remover aspas, prefixos comuns, etc.
        title = title.strip('"').strip("'").strip()
        # Remover prefixos comuns que o LLM pode adicionar
        prefixes_to_remove = ["Título:", "Title:", "Sugestão:", "Suggestion:"]
        for prefix in prefixes_to_remove:
            if title.lower().startswith(prefix.lower()):
                title = title[len(prefix):].strip()
        
        # Validar título
        if not title:
            title = request.current_title or "Widget"
        elif len(title) > 100:
            # Se muito longo, truncar
            title = title[:97] + "..."
        
        # Log do evento
        log_event(
            "widget_title_suggested",
            {
                "question": request.question[:200],
                "current_title": request.current_title,
                "suggested_title": title,
                "language": request.language,
                "has_data": bool(request.data_sample),
                "data_rows": len(request.data_sample) if request.data_sample else 0,
            },
        )
        
        return SuggestTitleResponse(title=title)
        
    except Exception as e:
        # Em caso de erro, retornar título atual ou fallback
        log_event(
            "widget_title_suggestion_error",
            {
                "question": request.question[:200],
                "current_title": request.current_title,
                "error": str(e)[:500],
            },
        )
        # Fallback: retornar título atual ou genérico
        fallback_title = request.current_title or "Widget"
        return SuggestTitleResponse(title=fallback_title)

