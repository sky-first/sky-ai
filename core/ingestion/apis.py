"""API description ingestion utilities."""

from typing import Dict, Any, List
import httpx
import json


def fetch_openapi_schema(api_url: str) -> Dict[str, Any]:
    """
    Fetch OpenAPI/Swagger schema from an API.

    Args:
        api_url: URL to OpenAPI schema (usually /openapi.json or /swagger.json)

    Returns:
        OpenAPI schema dictionary
    """
    with httpx.Client() as client:
        response = client.get(api_url)
        response.raise_for_status()
        return response.json()


def extract_endpoint_descriptions(
    openapi_schema: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Extract endpoint descriptions from OpenAPI schema.

    Args:
        openapi_schema: OpenAPI schema dictionary

    Returns:
        List of endpoint descriptions
    """
    descriptions = []

    paths = openapi_schema.get("paths", {})
    for path, methods in paths.items():
        for method, details in methods.items():
            if method.lower() in ["get", "post", "put", "delete", "patch"]:
                summary = details.get("summary", "")
                description = details.get("description", "")
                parameters = details.get("parameters", [])

                # Build description text
                desc_text = f"{method.upper()} {path}\n"
                if summary:
                    desc_text += f"Summary: {summary}\n"
                if description:
                    desc_text += f"Description: {description}\n"
                if parameters:
                    param_descs = [
                        f"{p.get('name')}: {p.get('description', '')}"
                        for p in parameters
                    ]
                    desc_text += f"Parameters: {', '.join(param_descs)}\n"

                descriptions.append(
                    {
                        "method": method.upper(),
                        "path": path,
                        "text": desc_text,
                        "metadata": {
                            "summary": summary,
                            "description": description,
                            "parameters": parameters,
                        },
                    }
                )

    return descriptions
