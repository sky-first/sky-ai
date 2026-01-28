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
        default="en", description="Language for the title (en, pt, es)"
    )


class SuggestTitleResponse(BaseModel):
    """Response with suggested title."""
    title: str = Field(..., description="Title suggested by AI")


@router.post("/suggest-title", response_model=SuggestTitleResponse)
async def suggest_widget_title(request: SuggestTitleRequest):
    """
    Suggests a better and more descriptive title for a widget based on the returned data.
    
    This function analyzes:
    - The original question
    - The returned data (sample)
    - The AI's textual answer (if available)
    - The current title (which might be generic)
    
    And generates a more specific and informative title.
    """
    try:
        # Create LLM instance
        llm = LangChainChatOpenAIProvider(
            model=settings.llm_model_formatter or "gpt-4o-mini",
            temperature=0.3,
            max_tokens=50,
        )
        
        # Prepare data sample as text
        data_text = ""
        if request.data_sample:
            sample = request.data_sample[:5]
            if sample:
                data_text = "\nReturned data (sample):\n"
                for i, row in enumerate(sample, 1):
                    row_str = ", ".join([f"{k}: {v}" for k, v in row.items()])
                    data_text += f"  Row {i}: {row_str}\n"
        
        # Build messages for the LLM
        system_msg = {
            "role": "system",
            "content": (
                "You are an expert in creating descriptive and concise titles for dashboard widgets.\n"
                "Analyze the question, the returned data, and suggest a clear and informative title.\n\n"
                "IMPORTANT RULES:\n"
                "- The title must be SHORT (maximum 60 characters)\n"
                "- It must clearly describe what the widget shows\n"
                "- Use ONLY English for the title, regardless of the user's language or input\n"
                "- Be SPECIFIC: avoid generic titles like 'Widget', 'Chart', 'Data', 'Graph'\n"
                "- Base it on the ACTUAL results returned, not just the question\n"
                "- If data shows specific metrics, mention them in the title\n"
                "- If data shows categories or dimensions, include them in the title\n"
                "- Return ONLY the title, no quotes, no explanations, no prefixes\n"
                "- Examples of good titles:\n"
                "  * 'Sales by Month' (not 'Sales Chart')\n"
                "  * 'Top 10 Customers' (not 'Customer Widget')\n"
                "  * 'Total Revenue 2024' (not 'KPI')\n"
                "  * 'Distribution by Region' (not 'Chart')\n"
            )
        }
        
        user_content = f"Original question: {request.question}\n\n"
        
        if request.current_title:
            user_content += f"Current title (generic): {request.current_title}\n\n"
        
        if data_text:
            user_content += data_text + "\n"
        
        if request.answer:
            answer_snippet = request.answer[:200]
            user_content += f"AI Answer: {answer_snippet}\n\n"
        
        user_content += (
            "Suggest a better and more descriptive title for this widget based on the information above "
            "(ALWAYS in English)."
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

