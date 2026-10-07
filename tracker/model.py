import json
import time

from groq import Groq

from .errors import TerminalServiceError, TransientServiceError

TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": "search_web", "description": "Search for relevant web pages.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "fetch_article", "description": "Fetch and extract a permitted public article URL.", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "finish", "description": "Finish with ranked, evidence-backed developments.", "parameters": {"type": "object", "properties": {"developments": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}, "summary": {"type": "string"}, "organization": {"type": "string"}, "technology": {"type": "string"}, "action": {"type": "string"}, "date": {"type": "string"}, "score": {"type": "number"}, "sources": {"type": "array", "items": {"type": "object", "properties": {"url": {"type": "string"}, "title": {"type": "string"}, "evidence": {"type": "string"}}, "required": ["url", "title", "evidence"]}}}, "required": ["title", "summary", "organization", "technology", "action", "date", "score", "sources"]}}}, "required": ["developments"]}}},
]


def call_model(
    api_key: str,
    model_name: str,
    messages: list[dict],
    *,
    force_finish: bool = False,
):
    client = Groq(api_key=api_key)
    tool_choice = (
        {"type": "function", "function": {"name": "finish"}}
        if force_finish
        else "auto"
    )
    last_error = None
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice=tool_choice,
                temperature=0,
            )
            choice = response.choices[0].message
            usage = getattr(response, "usage", None)
            tokens = int(getattr(usage, "total_tokens", 0) or 0)
            assistant = {"role": "assistant", "content": choice.content or ""}
            calls = []
            for call in choice.tool_calls or []:
                calls.append({
                    "id": call.id,
                    "name": call.function.name,
                    "args": json.loads(call.function.arguments),
                })
            if calls:
                assistant["tool_calls"] = [
                    {
                        "id": item["id"],
                        "type": "function",
                        "function": {
                            "name": item["name"],
                            "arguments": json.dumps(item["args"]),
                        },
                    }
                    for item in calls
                ]
            return assistant, calls, tokens
        except json.JSONDecodeError as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
        except Exception as exc:
            text = str(exc).lower()
            status_code = getattr(exc, "status_code", None)
            terminal_markers = (
                "invalid api key", "authentication", "payment required",
                "daily quota", "daily limit", "quota exceeded",
                "insufficient_quota", "model_not_found", "does not exist",
                "do not have access",
            )
            if status_code in {401, 402, 403} or any(
                marker in text for marker in terminal_markers
            ):
                raise TerminalServiceError(str(exc)) from exc
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise TransientServiceError(str(last_error)) from last_error
