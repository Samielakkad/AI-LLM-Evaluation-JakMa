"""Parse jak.ma endpoint responses across JSON, SSE, and plain-text modes."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterator, Optional

WORKERS_MARKER = re.compile(r"<<WORKERS:([^>]*)>>")


class ResponseParseError(ValueError):
    """Raised when an endpoint response violates the documented contract."""


@dataclass(frozen=True)
class ParsedEndpointResponse:
    response_text: str
    cited_ids: list[str]
    pass1_result: dict


def _parse_worker_marker(text: str) -> tuple[str, Optional[list[str]]]:
    matches = list(WORKERS_MARKER.finditer(text))
    if not matches:
        return text.strip(), None
    if len(matches) > 1:
        raise ResponseParseError("response contains more than one WORKERS marker")

    marker = matches[0]
    if text[marker.end() :].strip():
        raise ResponseParseError("WORKERS marker must be the final response content")

    cited_ids = [value.strip() for value in marker.group(1).split(",") if value.strip()]
    if len(cited_ids) != len(set(cited_ids)):
        raise ResponseParseError("WORKERS marker contains duplicate worker IDs")
    return text[: marker.start()].strip(), cited_ids


def _extract_pass1(value: object) -> Optional[dict]:
    if not isinstance(value, dict):
        return None
    for key in ("pass1", "pass1_result", "classification"):
        candidate = value.get(key)
        if isinstance(candidate, dict):
            return candidate
    for key in ("data", "payload", "result", "response"):
        nested = _extract_pass1(value.get(key))
        if nested is not None:
            return nested
    return None


def _validate_id_list(value: object, location: str) -> list[str]:
    if not isinstance(value, list):
        raise ResponseParseError(f"{location} must be an array")
    cited_ids = []
    for index, worker_id in enumerate(value):
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ResponseParseError(
                f"{location}[{index}] must be a non-empty string"
            )
        cited_ids.append(worker_id.strip())
    if len(cited_ids) != len(set(cited_ids)):
        raise ResponseParseError(f"{location} contains duplicate worker IDs")
    return cited_ids


def _extract_structured_ids(value: object) -> Optional[list[str]]:
    if not isinstance(value, dict):
        return None

    for key in ("cited_ids", "worker_ids"):
        if key in value:
            return _validate_id_list(value[key], key)

    if "workers_to_show" in value:
        workers = value["workers_to_show"]
        if not isinstance(workers, list):
            raise ResponseParseError("workers_to_show must be an array")
        worker_ids = []
        for index, worker in enumerate(workers):
            if isinstance(worker, str):
                worker_id = worker
            elif isinstance(worker, dict):
                worker_id = worker.get("worker_id", worker.get("id"))
            else:
                worker_id = None
            if not isinstance(worker_id, str) or not worker_id.strip():
                raise ResponseParseError(
                    f"workers_to_show[{index}] must identify a worker"
                )
            worker_ids.append(worker_id.strip())
        if len(worker_ids) != len(set(worker_ids)):
            raise ResponseParseError("workers_to_show contains duplicate worker IDs")
        return worker_ids

    for key in ("data", "payload", "result", "response"):
        nested = _extract_structured_ids(value.get(key))
        if nested is not None:
            return nested
    return None


def _extract_full_text(value: object) -> Optional[str]:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return None

    for key in ("message_darija", "response_text", "response", "text", "content"):
        candidate = value.get(key)
        if isinstance(candidate, str):
            return candidate

    message = value.get("message")
    if isinstance(message, str):
        return message
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]

    choices = value.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0]
        if isinstance(choice, dict):
            nested = _extract_full_text(choice)
            if nested is not None:
                return nested

    for key in ("data", "payload", "result", "response"):
        nested = _extract_full_text(value.get(key))
        if nested is not None:
            return nested
    return None


def _merge_ids(
    marker_ids: Optional[list[str]],
    structured_ids: Optional[list[str]],
) -> list[str]:
    if marker_ids is None and structured_ids is None:
        raise ResponseParseError(
            "response does not declare worker IDs with a marker or structured field"
        )
    if marker_ids is not None and structured_ids is not None:
        if marker_ids != structured_ids:
            raise ResponseParseError(
                "WORKERS marker does not match structured worker IDs"
            )
        return marker_ids
    return marker_ids if marker_ids is not None else structured_ids or []


def _parse_json_response(body: str) -> ParsedEndpointResponse:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise ResponseParseError(f"response is not valid JSON: {error}") from error

    response_text = _extract_full_text(payload)
    if response_text is None:
        raise ResponseParseError("JSON response does not contain response text")
    response_text, marker_ids = _parse_worker_marker(response_text)
    structured_ids = _extract_structured_ids(payload)
    pass1_result = _extract_pass1(payload) or {}
    return ParsedEndpointResponse(
        response_text=response_text,
        cited_ids=_merge_ids(marker_ids, structured_ids),
        pass1_result=pass1_result,
    )


def _iter_sse_data(body: str) -> Iterator[str]:
    data_lines: list[str] = []
    for line in body.splitlines():
        if not line:
            if data_lines:
                yield "\n".join(data_lines)
                data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if separator and field == "data":
            data_lines.append(value[1:] if value.startswith(" ") else value)
    if data_lines:
        yield "\n".join(data_lines)


def _extract_sse_text(value: object) -> tuple[str, Optional[str]]:
    """Return ``(incremental_text, complete_text)`` from one SSE payload."""
    if isinstance(value, str):
        return value, None
    if not isinstance(value, dict):
        return "", None

    for key in ("message_darija", "response_text"):
        candidate = value.get(key)
        if isinstance(candidate, str):
            return "", candidate

    token = value.get("token")
    if isinstance(token, str):
        return token, None
    text = value.get("text")
    if isinstance(text, str):
        return text, None
    delta = value.get("delta")
    if isinstance(delta, str):
        return delta, None
    if isinstance(delta, dict) and isinstance(delta.get("content"), str):
        return delta["content"], None

    choices = value.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0]
        if isinstance(choice, dict):
            return _extract_sse_text(choice)

    data = value.get("data")
    if isinstance(data, (dict, str)):
        return _extract_sse_text(data)
    return "", None


def _parse_sse_response(body: str) -> ParsedEndpointResponse:
    chunks: list[str] = []
    complete_text: Optional[str] = None
    structured_ids: Optional[list[str]] = None
    pass1_result: dict = {}
    saw_data = False

    for data in _iter_sse_data(body):
        saw_data = True
        if data.strip() == "[DONE]":
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            chunks.append(data)
            continue

        event_pass1 = _extract_pass1(payload)
        if event_pass1 is not None:
            pass1_result = event_pass1

        event_ids = _extract_structured_ids(payload)
        if event_ids is not None:
            if structured_ids is not None and structured_ids != event_ids:
                raise ResponseParseError("SSE events contain conflicting worker IDs")
            structured_ids = event_ids

        chunk, event_complete_text = _extract_sse_text(payload)
        if chunk:
            chunks.append(chunk)
        if event_complete_text is not None:
            complete_text = event_complete_text

    if not saw_data:
        raise ResponseParseError("SSE response does not contain data events")

    response_text = complete_text if complete_text is not None else "".join(chunks)
    response_text, marker_ids = _parse_worker_marker(response_text)
    return ParsedEndpointResponse(
        response_text=response_text,
        cited_ids=_merge_ids(marker_ids, structured_ids),
        pass1_result=pass1_result,
    )


def _looks_like_sse(body: str) -> bool:
    first_content_line = next(
        (line for line in body.splitlines() if line and not line.startswith(":")),
        "",
    )
    return first_content_line.startswith(("data:", "event:", "id:", "retry:"))


def parse_endpoint_response(
    body: str,
    content_type: str = "",
) -> ParsedEndpointResponse:
    """Parse a complete endpoint body according to its media type and shape."""
    media_type = content_type.partition(";")[0].strip().lower()
    if media_type == "text/event-stream" or _looks_like_sse(body):
        return _parse_sse_response(body)
    if media_type == "application/json" or media_type.endswith("+json"):
        return _parse_json_response(body)

    stripped = body.lstrip()
    if stripped.startswith(("{", "[", '"')):
        return _parse_json_response(body)

    response_text, marker_ids = _parse_worker_marker(body)
    return ParsedEndpointResponse(
        response_text=response_text,
        cited_ids=_merge_ids(marker_ids, None),
        pass1_result={},
    )
