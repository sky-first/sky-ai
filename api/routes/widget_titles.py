import logging
import json as _json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.llm.providers import LangChainChatOpenAIProvider, OllamaProvider
from core.logging_utils import log_event
from config.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/widgets", tags=["widgets"])


def _make_formatter_llm(temperature: float, max_tokens: int):
    # Respect AI_PROVIDER. Previously this route hard-instantiated OpenAI,
    # which made every widget-title / infographic call hit gpt-4o-mini even
    # when the rest of the stack was on Ollama — silently burning tokens.
    if settings.use_local_models:
        return OllamaProvider(
            model=settings.llm_model_formatter_local,
            base_url=settings.ollama_base_url,
            temperature=temperature,
            num_ctx=getattr(settings, "ollama_num_ctx_formatter", 4096),
        )
    return LangChainChatOpenAIProvider(
        model=settings.llm_model_formatter or "gpt-4o-mini",
        temperature=temperature,
        max_tokens=max_tokens,
    )


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
        # ✅ FIX: Fast-path fallback for error states
        # If the answer indicates a failure and there's no data, don't ask LLM (it hallucinates).
        if request.answer:
            error_keywords = [
                "error",
                "impossible",
                "sorry",
                "i can't",
                "i cannot",
                "fail",
                "exception",
            ]
            ans_lower = request.answer.lower()
            if any(k in ans_lower for k in error_keywords) and not request.data_sample:
                log_event(
                    "widget_title_error_fallback",
                    {"reason": "detected_error_in_answer"},
                )
                return SuggestTitleResponse(title=request.current_title or "Widget")

        # Create LLM instance (respects AI_PROVIDER)
        llm = _make_formatter_llm(temperature=0.3, max_tokens=50)

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
            ),
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

        user_msg = {"role": "user", "content": user_content}

        # Chamar LLM
        resp = llm.invoke([system_msg, user_msg])
        title = getattr(resp, "content", "").strip()

        # Limpar título: remover aspas, prefixos comuns, etc.
        title = title.strip('"').strip("'").strip()
        # Remover prefixos comuns que o LLM pode adicionar
        prefixes_to_remove = ["Título:", "Title:", "Sugestão:", "Suggestion:"]
        for prefix in prefixes_to_remove:
            if title.lower().startswith(prefix.lower()):
                title = title[len(prefix) :].strip()

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


# ==========================
# Infographic Generation
# ==========================


class GenerateInfographicRequest(BaseModel):
    """Request for generating structured infographic data."""

    question: str = Field(..., description="The original analytical question")
    answer: str = Field(..., description="The AI's textual answer/analysis")
    data_sample: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Data sample rows (max ~15)"
    )
    language: str = Field(default="en", description="Language (en, pt, es)")
    style: str = Field(
        default="mix", description="Infographic style: textual, visual, mix"
    )


@router.post("/infographic")
async def generate_infographic(request: GenerateInfographicRequest):
    """
    Generate structured data for an infographic widget.

    Uses the LLM to transform a question + answer + data into a rich
    structured JSON matching the frontend InfographicData interface.
    """
    logger.info(f"Generating infographic for question: {request.question[:100]}...")
    try:
        llm = _make_formatter_llm(temperature=0.4, max_tokens=2000)

        # Prepare data context
        data_text = ""
        if request.data_sample:
            sample = request.data_sample[:10]
            if sample:
                data_text = "\nData sample:\n"
                for i, row in enumerate(sample, 1):
                    row_str = ", ".join([f"{k}: {v}" for k, v in row.items()])
                    data_text += f"  Row {i}: {row_str}\n"

        system_msg = {
            "role": "system",
            "content": (
                "You are a senior data analyst. Your goal is to generate a RICH, FULLY POPULATED infographic JSON.\n"
                "The user hates empty white space. You MUST fill AS MANY fields as possible, even if you have to infer "
                "or estimate reasonable labels/trends based on the context of the answer.\n\n"
                "INPUTS:\n"
                "- Question, Answer, Optional Data Rows.\n\n"
                "OUTPUT FORMAT (JSON):\n"
                "{\n"
                '  "title": "Short headline (max 40 chars)",\n'
                '  "subtitle": "Category badge (e.g. REVENUE, ANALYSIS)",\n'
                '  "mainValue": "Primary metric (e.g. $1.2M, 45%)",\n'
                '  "mainValueLabel": "Context (e.g. vs last month)",\n'
                '  "summary": "3 sentences summarizing the key insight.",\n'
                '  "highlightedValue": "A second important number or phrase",\n'
                '  "marginLabel": "KPI 1 Label (e.g. Avg Order)",\n'
                '  "marginValue": "KPI 1 Value (e.g. $150)",\n'
                '  "cacLabel": "KPI 2 Label (e.g. Conversion)",\n'
                '  "cacValue": "KPI 2 Value (e.g. 5%)",\n'
                '  "trajectoryTitle": "Trend / Breakdown",\n'
                '  "trajectoryData": [{"name": "Jan", "value": 100, "revenue": 100, "target": 90}, ...],\n'
                '  "recordHighLabel": "Insight about the chart",\n'
                '  "drivers": [\n'
                '    {"name": "Driver", "impact": "High", "description": "Why?"}\n'
                "  ],\n"
                '  "whyTitle": "Why is this happening?",\n'
                '  "whyContent": "Explanation of root causes.",\n'
                '  "whyChartData": [{"x": "Reason", "y": 30}, ...],\n'
                '  "breakdownTitle": "Categorical Breakdown",\n'
                '  "breakdownData": [{"label": "Category", "value": 45, "color": "bg-blue-500"}],\n'
                '  "strategicTitle": "Strategic Step",\n'
                '  "strategicContent": "What should we do next?",\n'
                '  "outlookTitle": "Forecast / Impact",\n'
                '  "outlookContent": "Future projection.",\n'
                '  "outlookChartData": [{"name": "Scenario A", "value": 60}, ...],\n'
                '  "outlookChartCenterValue": "Summary",\n'
                '  "outlookChartCenterLabel": "Label"\n'
                "}\n\n"
                "MANDATORY RULES:\n"
                "1. DO NOT return nulls for 'margin', 'cac', 'drivers', 'why', or 'strategic' sections unless truly impossible.\n"
                "2. If exact numbers for KPIs (margin/cac) are not in the data, try to extract secondary metrics from the text.\n"
                "3. CHART POPULATION (CRITICAL): The user hates empty charts. ALWAYS POPULATE 'trajectoryData', 'whyChartData', 'outlookChartData', and 'breakdownData' with at least 3 items each. If exact data isn't in `data_sample`, you MUST INFER HIGHLY RELEVANT, PLAUSIBLE BUSINESS DATA based on the `question`. (e.g., if the question is about 'Refunds', break down by 'Product Defect, Shipping Delay, Change of Mind'. NEVER use generic IT placeholders like 'Kubernetes' or 'Serverless' unless the question is about IT infrastructure!).\n"
                "   - 'whyChartData' items MUST have 'x' (string reason) and 'y' (number impact).\n"
                "   - 'breakdownData' items MUST have 'label' (string category) and 'value' (number percentage 0-100).\n"
                "4. For 'drivers', ALWAYS generate at least 2 key factors based on the text.\n"
                "5. For 'strategicContent', ALWAYS suggest a logical next step.\n"
                "6. trajectoryData should have objects with 'name' (string) and 'value' (number). Optionally 'revenue' (number) and 'target' (number).\n"
                "7. ALWAYS respond in English.\n"
            ),
        }

        user_content = f"Question: {request.question}\n\n"
        user_content += f"AI Analysis:\n{request.answer[:1500]}\n\n"
        if data_text:
            user_content += data_text + "\n"
        user_content += f"Style preference: {request.style}\n"
        user_content += "\nGenerate the infographic JSON:"

        user_msg = {"role": "user", "content": user_content}

        resp = llm.invoke([system_msg, user_msg])
        raw = getattr(resp, "content", "").strip()

        # Clean markdown fences if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            # Remove first and last lines (```json and ```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            raw = "\n".join(lines)

        result = _json.loads(raw)
        logger.info(
            f"Successfully generated infographic JSON with {len(result)} fields. RAW JSON: {raw}"
        )

        log_event(
            "infographic_generated",
            {
                "question": request.question[:200],
                "style": request.style,
                "has_data": bool(request.data_sample),
                "fields_returned": len(result),
            },
        )

        return result

    except Exception as e:
        log_event(
            "infographic_generation_error",
            {
                "question": request.question[:200],
                "style": request.style,
                "error": str(e),
            },
        )
        logger.error(f"Infographic generation failed: {str(e)}", exc_info=True)
        # Return a minimal fallback so the frontend doesn't crash
        return {
            "title": "Analysis",
            "subtitle": request.style.upper(),
            "summary": (
                request.answer[:500]
                if request.answer
                else "Analysis could not be generated."
            ),
            "whyTitle": "Details",
            "whyContent": request.answer[:300] if request.answer else "",
        }
