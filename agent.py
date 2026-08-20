import json
import os
import re
from typing import Any

from dotenv import load_dotenv
import httpx

from tools import TOOL_ARG_MODELS, TOOL_REGISTRY, TOOL_SCHEMAS


load_dotenv()


SYSTEM_PROMPT = (
    "You are the Obliq-io compliance agent. "
    "Only use facts returned by tools. Never invent client details, dates, or documents. "
    "You must always call get_missing_docs and get_upcoming_deadlines before you decide "
    "whether to call trigger_reminder. "
    "If both checks are clean, do not call trigger_reminder. "
    "Return a concise JSON object with keys: summary, actions, and final_status."
)


def _sanitize_gemini_schema(node: Any) -> Any:
    if isinstance(node, dict):
        cleaned: dict[str, Any] = {}
        for key, value in node.items():
            if key in {"additionalProperties", "default"}:
                continue
            cleaned[key] = _sanitize_gemini_schema(value)
        return cleaned
    if isinstance(node, list):
        return [_sanitize_gemini_schema(item) for item in node]
    return node


def _build_gemini_function_declarations() -> list[dict[str, Any]]:
    declarations: list[dict[str, Any]] = []
    for tool in TOOL_SCHEMAS:
        function = tool["function"]
        declaration = {
            "name": function["name"],
            "description": function["description"],
            "parameters": _sanitize_gemini_schema(function["parameters"]),
        }
        declarations.append(declaration)
    return declarations


async def _gemini_generate_content(
    api_key: str,
    model: str,
    contents: list[dict[str, Any]],
) -> dict[str, Any]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contents,
        "tools": [
            {
                "functionDeclarations": _build_gemini_function_declarations(),
            }
        ],
        "generationConfig": {"temperature": 0},
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, params={"key": api_key}, json=payload)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"Gemini API error: {exc.response.text}") from exc
        return response.json()


def _extract_function_calls(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [part["functionCall"] for part in parts if "functionCall" in part]


def _strip_markdown_formatting(text: str) -> str:
    fenced_match = re.fullmatch(
        r"\s*```[^\r\n]*\r?\n?(.*?)\r?\n?```\s*",
        text,
        flags=re.DOTALL,
    )
    if fenced_match:
        return fenced_match.group(1).strip()

    inline_match = re.fullmatch(r"\s*`(.*?)`\s*", text, flags=re.DOTALL)
    if inline_match:
        return inline_match.group(1).strip()

    return text.strip()


def _extract_text(parts: list[dict[str, Any]]) -> str:
    text_parts = [part.get("text", "") for part in parts if "text" in part]
    return "\n".join(item for item in text_parts if item).strip()


async def _execute_tool(
    tool_name: str,
    arguments: dict[str, Any],
    docs_checked: bool,
    deadlines_checked: bool,
) -> dict[str, Any]:
    if tool_name not in TOOL_REGISTRY:
        return {"error": f"Unknown tool: {tool_name}"}

    # Enforce mandatory verification before any reminder operation.
    if tool_name == "trigger_reminder" and not (docs_checked and deadlines_checked):
        return {
            "error": (
                "Verification rule violation: trigger_reminder requires both "
                "get_missing_docs and get_upcoming_deadlines to run first."
            )
        }

    try:
        validated = TOOL_ARG_MODELS[tool_name](**arguments)
        result = await TOOL_REGISTRY[tool_name](**validated.model_dump())
        return result
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


async def run_compliance_agent(client_id: str) -> dict[str, Any]:
    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to your environment or .env file."
        )

    model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

    contents: list[dict[str, Any]] = [
        {
            "role": "user",
            "parts": [{"text": f"Run compliance check for client {client_id}."}],
        }
    ]

    execution_log: list[dict[str, Any]] = []
    docs_checked = False
    deadlines_checked = False
    max_turns = 10

    for turn in range(1, max_turns + 1):
        response_json = await _gemini_generate_content(
            api_key=gemini_api_key,
            model=model,
            contents=contents,
        )
        candidates = response_json.get("candidates", [])
        if not candidates:
            raise RuntimeError(f"Gemini returned no candidates: {response_json}")

        model_content = candidates[0].get("content", {"role": "model", "parts": []})
        parts = model_content.get("parts", [])
        contents.append(model_content)

        function_calls = _extract_function_calls(parts)
        if function_calls:
            response_parts: list[dict[str, Any]] = []

            for function_call in function_calls:
                tool_name = function_call.get("name", "")
                tool_args = function_call.get("args", {})
                if not isinstance(tool_args, dict):
                    tool_args = {}

                tool_result = await _execute_tool(
                    tool_name=tool_name,
                    arguments=tool_args,
                    docs_checked=docs_checked,
                    deadlines_checked=deadlines_checked,
                )

                if tool_name == "get_missing_docs":
                    docs_checked = True
                if tool_name == "get_upcoming_deadlines":
                    deadlines_checked = True

                execution_log.append(
                    {
                        "turn": turn,
                        "tool": tool_name,
                        "arguments": tool_args,
                        "result": tool_result,
                    }
                )

                response_parts.append(
                    {
                        "functionResponse": {
                            "name": tool_name,
                            "response": {"result": tool_result},
                        }
                    }
                )

            contents.append({"role": "user", "parts": response_parts})
            continue

        final_text = _strip_markdown_formatting(_extract_text(parts)) or "{}"
        try:
            final_payload = json.loads(final_text)
        except json.JSONDecodeError:
            final_payload = {
                "summary": final_text,
                "actions": execution_log,
                "final_status": "completed_with_unstructured_response",
            }

        return {
            "client_id": client_id,
            "model": model,
            "verification": {
                "documents_checked": docs_checked,
                "deadlines_checked": deadlines_checked,
            },
            "execution_log": execution_log,
            "agent_result": final_payload,
        }

    return {
        "client_id": client_id,
        "model": model,
        "verification": {
            "documents_checked": docs_checked,
            "deadlines_checked": deadlines_checked,
        },
        "execution_log": execution_log,
        "agent_result": {
            "summary": "Agent hit turn limit before producing a final answer.",
            "actions": execution_log,
            "final_status": "incomplete",
        },
    }
