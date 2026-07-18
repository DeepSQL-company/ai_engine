import json
from typing import Any


def format_sse(event: dict[str, Any]) -> str:
    event_type = event.get("type", "message")
    data = json.dumps(event, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {data}\n\n"
