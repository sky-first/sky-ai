"""
API Specialist — answers questions by calling external REST APIs.

For connectors like HubSpot, Jira, Zendesk, Salesforce — translates
natural language questions into API requests, executes them, and
formats the response.

This specialist uses the connector metadata (endpoints, fields) from
the backend's connector registry to understand what each API can do.
"""

from __future__ import annotations
import json
import logging
from typing import Any, Dict, List, Optional
from core.llm._brain_prompt import prepend_brain_context
from core.logging_utils import log_event

logger = logging.getLogger("dataassistant")

SYSTEM_PROMPT = """You are an API integration specialist.
You have access to an external API ({api_name}) with the endpoints described below.
Your job is to answer the user's question by determining which API endpoint to call
and what parameters to use.

IMPORTANT: You must respond with a JSON object describing the API call to make.
The format is:
```json
{{
    "endpoint": "/path/to/endpoint",
    "method": "GET",
    "params": {{"key": "value"}},
    "description": "Brief description of what this call does"
}}
```

If the question cannot be answered with the available endpoints, respond with:
```json
{{
    "error": "This question requires data that is not available through the {api_name} API."
}}
```

## Available API Endpoints
{endpoints_text}

## API Base URL
{base_url}
"""

ANSWER_PROMPT = """You are a data analyst. The user asked a question and we queried an external API.
Summarize the results in natural language. Be specific with numbers and data.

User question: {question}
API called: {api_name} {endpoint}
API response (first 2000 chars):
{response_preview}

Respond in the same language as the user's question.
"""


def _format_endpoints(endpoints: List[Dict[str, Any]]) -> str:
    if not endpoints:
        return "(No endpoints documented)"
    lines = []
    for ep in endpoints:
        method = ep.get("method", "GET").upper()
        path = ep.get("path", ep.get("endpoint", ""))
        desc = ep.get("description", "")
        fields = ep.get("fields", ep.get("parameters", []))
        line = f"- {method} {path}: {desc}"
        if fields:
            field_names = [f.get("name", f.get("key", "")) for f in fields if isinstance(f, dict)]
            if field_names:
                line += f" (params: {', '.join(field_names)})"
        lines.append(line)
    return "\n".join(lines)


def run_api_specialist(
    state: Dict[str, Any],
    llm: Any,
    api_config: Dict[str, Any],
    data_source: Any = None,
) -> Dict[str, Any]:
    """
    API specialist LangGraph node.

    1. Reads API metadata (endpoints, auth) from api_config
    2. Asks LLM to generate an API request spec
    3. Executes the request
    4. Asks LLM to summarize the results
    """
    question = state.get("question", "")
    api_name = api_config.get("name", "External API")
    base_url = api_config.get("base_url", "")
    endpoints = api_config.get("endpoints", [])

    log_event("api_specialist_start", {
        "question": question[:100],
        "api_name": api_name,
        "num_endpoints": len(endpoints),
    })

    if not endpoints:
        state["answer"] = f"The {api_name} connector has no documented endpoints yet. Configure the API metadata first."
        state["data"] = []
        state["sql"] = None
        return state

    # Step 1: Ask LLM to generate API request spec
    spec_prompt = SYSTEM_PROMPT.format(
        api_name=api_name,
        base_url=base_url,
        endpoints_text=_format_endpoints(endpoints),
    )

    try:
        response = llm.invoke([
            {"role": "system", "content": spec_prompt},
            {"role": "user", "content": prepend_brain_context(question, state)},
        ])
        spec_text = response.content if hasattr(response, "content") else str(response)

        # Parse the JSON spec from the LLM response
        # Extract JSON from markdown code blocks if present
        if "```json" in spec_text:
            spec_text = spec_text.split("```json")[1].split("```")[0].strip()
        elif "```" in spec_text:
            spec_text = spec_text.split("```")[1].split("```")[0].strip()

        spec = json.loads(spec_text)

        if spec.get("error"):
            state["answer"] = spec["error"]
            state["data"] = []
            state["sql"] = None
            return state

    except Exception as e:
        logger.error(f"API specialist LLM spec generation error: {e}")
        state["answer"] = f"I couldn't determine which API call to make: {e}"
        state["data"] = []
        state["sql"] = None
        return state

    # Step 2: Execute the API call
    endpoint = spec.get("endpoint", "")
    method = spec.get("method", "GET").upper()
    params = spec.get("params", {})

    log_event("api_specialist_executing", {
        "api_name": api_name,
        "method": method,
        "endpoint": endpoint,
        "params": str(params)[:200],
    })

    try:
        if data_source and hasattr(data_source, "run_query"):
            # Use the data source's run_query with the spec
            api_result = data_source.run_query(json.dumps(spec))
        else:
            # Direct HTTP call as fallback
            import httpx
            url = f"{base_url.rstrip('/')}{endpoint}"
            with httpx.Client(timeout=15) as client:
                if method == "GET":
                    r = client.get(url, params=params)
                else:
                    r = client.post(url, json=params)
                r.raise_for_status()
                api_result = r.json()
    except Exception as e:
        logger.error(f"API specialist execution error: {e}")
        state["answer"] = f"The API call to {api_name} {endpoint} failed: {e}"
        state["data"] = []
        state["sql"] = None
        return state

    # Step 3: Summarize the results
    response_preview = json.dumps(api_result, default=str)[:2000]

    try:
        answer_prompt = ANSWER_PROMPT.format(
            question=question,
            api_name=api_name,
            endpoint=f"{method} {endpoint}",
            response_preview=response_preview,
        )
        response = llm.invoke([
            {"role": "system", "content": answer_prompt},
            {"role": "user", "content": prepend_brain_context(question, state)},
        ])
        answer = response.content if hasattr(response, "content") else str(response)
    except Exception as e:
        answer = f"API returned data but I couldn't summarize it: {response_preview[:500]}"

    log_event("api_specialist_done", {
        "api_name": api_name,
        "endpoint": endpoint,
        "answer_preview": answer[:200] if answer else "",
    })

    state["answer"] = answer
    state["data"] = api_result if isinstance(api_result, list) else [api_result] if api_result else []
    state["sql"] = f"API: {method} {base_url}{endpoint}"
    state["generated_title"] = f"{api_name}: {question[:50]}"

    return state
