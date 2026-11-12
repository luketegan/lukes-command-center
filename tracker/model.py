import json
import time

from groq import Groq

from .errors import TerminalServiceError, TransientServiceError
from .retry import is_daily_limit, retry_wait

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
    required_tool: str | None = None,
    max_retries: int = 2,
    tools: list[dict] | None = None,
    timeout: float = 60,
    deadline: float | None = None,
    max_completion_tokens: int | None = None,
    reasoning_effort: str | None = None,
):
    # This function owns the retry policy, so the SDK must not retry as well.
    client = Groq(api_key=api_key, max_retries=0, timeout=timeout)
    tool_choice = (
        {"type": "function", "function": {"name": required_tool}}
        if required_tool
        else "auto"
    )
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                tools=tools or TOOL_SCHEMAS,
                tool_choice=tool_choice,
                temperature=0,
                # Groq counts the reply allowance against the per-minute limit, so keep it small.
                **({"max_completion_tokens": max_completion_tokens} if max_completion_tokens else {}),
                **({"extra_body": {"reasoning_effort": reasoning_effort}} if reasoning_effort else {}),
            )
            choice = response.choices[0].message
            usage = getattr(response, "usage", None)
            tokens = int(getattr(usage, "total_tokens", 0) or 0)
            assistant = {"role": "assistant", "content": choice.content or ""}
            calls = []
            for call in choice.tool_calls or []:
                args = json.loads(call.function.arguments)
                calls.append({
                    "id": call.id,
                    "name": call.function.name,
                    "args": args if isinstance(args, dict) else {},
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
            if attempt < max_retries:
                time.sleep(retry_wait(attempt))
        except Exception as exc:
            message = str(exc)
            text = message.lower()
            status_code = getattr(exc, "status_code", None)
            if status_code == 400 and "tool call validation" in text and tool_choice not in ("auto", "required"):
                # The model ignored the forced tool. Let it pick any tool rather than failing the step.
                tool_choice = "required"
                last_error = exc
                continue
            terminal_markers = (
                "invalid api key", "authentication", "payment required",
                "model_not_found", "does not exist", "do not have access",
            )
            is_terminal = (
                status_code in {401, 402, 403}
                or is_daily_limit(text)
                or (status_code != 429 and any(marker in text for marker in terminal_markers))
            )
            if is_terminal:
                raise TerminalServiceError(message) from exc
            last_error = exc
            if attempt < max_retries:
                headers = getattr(getattr(exc, "response", None), "headers", None) or {}
                wait = retry_wait(attempt, message, headers.get("retry-after"))
                if deadline is not None and time.monotonic() + wait >= deadline:
                    break  # Waiting would pass the caller's deadline.
                time.sleep(wait)
    raise TransientServiceError(str(last_error)) from last_error
