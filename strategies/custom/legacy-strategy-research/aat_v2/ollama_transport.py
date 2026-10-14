"""Ollama HTTP transport for AAT-V2 TRAINING.

Talks to loopback ``http://127.0.0.1:11434`` by default. A non-loopback
``--base-url`` (RunPod GPU or similar) is allowed only when the caller opts
into remote hosts. Live HTTP still requires ``--allow-live-ollama``. Native
Ollama ``/api/chat`` is the TRAINING API; OpenAI-compat ``/v1`` is not used.

Thinking is disabled when the runtime honors ``think: false``. Arm B/C/D use
the five-field Actor JSON schema at the registered 256-token budget. Arm E
reuses the compact closed-enum parser.

Ollama does not always return OpenAI-style ``usage``. When ``prompt_eval_count``
and ``eval_count`` are present they are recorded as ``OLLAMA_REPORTED``. When
they are missing the transport labels a conservative utf-8 bytes/4 estimate as
``BYTE_PROXY_ESTIMATE``. Estimates are never treated as vendor billing.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..aat_v1.providers import OLLAMA, OLLAMA_USER_AGENT
from ..athena_adapter.contracts import canonical_hash
from .arms import E_DELIBERATION
from .deliberation import (
    DELIBERATION_OUTPUT_TOKENS,
    DELIBERATION_TURN_ROLES,
    compact_user_payload,
    parse_deliberation_turn,
    raw_content_snippet,
    turn_system_prompt,
)
from .ollama_identity import CHAT_PATH, DEFAULT_BASE_URL, DEFAULT_MODEL_ID, TRAINING_PROMPT

Transport = Callable[[Mapping[str, Any]], Mapping[str, Any]]

USAGE_REPORTED = "OLLAMA_REPORTED"
USAGE_ESTIMATED = "BYTE_PROXY_ESTIMATE"
BYTES_PER_TOKEN_PROXY = 4
LEGAL_ACTIONS = ("PASS", "ENTER_REDUCED", "ENTER_STANDARD", "ENTER_HIGH_CONVICTION")
ACTOR_DECISION_KEYS = ("action", "confidence", "horizon", "invalidation", "rationale")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_RETRIES = 3
RETRY_STATUSES = {408, 429, 500, 502, 503, 504}


class OllamaTransportError(ValueError):
    """The local Ollama transport cannot proceed safely."""


def is_loopback_base_url(base_url: str) -> bool:
    """True when ``base_url`` targets loopback (including an SSH tunnel)."""
    if not isinstance(base_url, str) or not base_url.strip():
        return False
    host = (urlparse(base_url.strip()).hostname or "").lower()
    return host in LOOPBACK_HOSTS


def transport_host_scope(base_url: str) -> str:
    """Return ``loopback`` or ``remote`` for receipts. Does not authorize live HTTP."""
    return "loopback" if is_loopback_base_url(base_url) else "remote"


def loopback_chat_url(base_url: str = DEFAULT_BASE_URL) -> str:
    """Return the chat endpoint, refusing anything that is not loopback HTTP."""
    return ollama_chat_url(base_url, allow_remote=False)


def ollama_chat_url(base_url: str = DEFAULT_BASE_URL, *, allow_remote: bool = False) -> str:
    """Return native ``/api/chat``. Remote hosts require ``allow_remote=True``."""
    if not isinstance(base_url, str) or not base_url.strip():
        raise OllamaTransportError("Ollama base URL is unusable")
    parsed = urlparse(base_url.strip())
    if parsed.username or parsed.password:
        raise OllamaTransportError("Ollama TRAINING transport refuses URLs with credentials")
    host = (parsed.hostname or "").lower()
    if not host:
        raise OllamaTransportError("Ollama base URL is missing a host")
    if parsed.path not in ("", "/", CHAT_PATH):
        raise OllamaTransportError("Ollama TRAINING transport only uses /api/chat")
    hostname = parsed.hostname
    if hostname is None:
        raise OllamaTransportError("Ollama base URL is missing a host")
    loopback = host in LOOPBACK_HOSTS
    if loopback:
        if parsed.scheme != "http":
            raise OllamaTransportError("Ollama TRAINING transport is loopback HTTP only")
        port = parsed.port or 11434
        if hostname == "::1":
            return f"http://[::1]:{port}{CHAT_PATH}"
        return f"http://{hostname}:{port}{CHAT_PATH}"
    if not allow_remote:
        raise OllamaTransportError("Ollama TRAINING transport refuses non-loopback hosts")
    if parsed.scheme not in {"http", "https"}:
        raise OllamaTransportError("remote Ollama TRAINING transport is HTTP or HTTPS only")
    # Explicit ports are preserved. HTTPS remotes without a port keep the
    # scheme default (443) so RunPod HTTPS proxies are not rewritten to
    # :11434. Bare HTTP remotes still default to Ollama's 11434.
    if parsed.port is not None:
        port: int | None = parsed.port
    elif parsed.scheme == "http":
        port = 11434
    else:
        port = None
    return f"{parsed.scheme}://{_format_hostport(hostname, port)}{CHAT_PATH}"


def build_ollama_payload(
    packet: Mapping[str, Any],
    *,
    max_output_tokens: int,
    model_id: str = DEFAULT_MODEL_ID,
    arm: str | None = None,
    turn: str | None = None,
    system_prompt: str | None = None,
    prior_turns: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Ollama ``/api/chat`` body with thinking disabled and JSON format pinned."""
    if max_output_tokens < 1:
        raise OllamaTransportError("output token budget must be positive")
    if not isinstance(model_id, str) or not model_id.strip():
        raise OllamaTransportError("Ollama model id is unusable")
    if arm == E_DELIBERATION or turn is not None:
        if arm not in (E_DELIBERATION, None) or turn is None:
            raise OllamaTransportError("E-arm TRAINING requires a deliberation turn")
        if max_output_tokens != DELIBERATION_OUTPUT_TOKENS:
            raise OllamaTransportError("E-arm turns must keep the 64-token budget")
        system = turn_system_prompt(turn)
        user: Mapping[str, Any] = compact_user_payload(packet, turn=turn, prior_turns=prior_turns)
    else:
        system = TRAINING_PROMPT if system_prompt is None else system_prompt
        user = packet
    return {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(user, sort_keys=True, separators=(",", ":")),
            },
        ],
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"num_predict": max_output_tokens},
    }


def ollama_http_headers() -> dict[str, str]:
    """JSON chat headers with a deliberate User-Agent.

    urllib adds ``Python-urllib/3.x`` when User-Agent is omitted. RunPod HTTPS
    proxies 403 that default, so TRAINING always sets ``OLLAMA_USER_AGENT``.
    """
    headers = dict(OLLAMA.build_headers(""))
    headers["User-Agent"] = OLLAMA_USER_AGENT
    return headers


def live_ollama_transport(
    *,
    base_url: str = DEFAULT_BASE_URL,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    allow_remote: bool = False,
) -> Transport:
    """POST chat completions to Ollama. Timeouts/retries are GPU-oriented."""
    endpoint = ollama_chat_url(base_url, allow_remote=allow_remote)
    if timeout_seconds < 1 or retries < 1:
        raise OllamaTransportError("Ollama timeout and retries must be positive")
    headers = ollama_http_headers()

    def _send(payload: Mapping[str, Any]) -> dict[str, Any]:
        if payload.get("think") is not False or payload.get("stream") is not False:
            raise OllamaTransportError("Ollama TRAINING payload must disable thinking and streaming")
        body = json.dumps(payload).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            request = Request(
                endpoint,
                data=body,
                headers=headers,
                method="POST",
            )
            try:
                # URL is validated by ollama_chat_url (http/https, no credentials).
                with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310
                    parsed = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                last_error = exc
                if exc.code not in RETRY_STATUSES or attempt >= retries:
                    raise OllamaTransportError(
                        f"Ollama TRAINING failed closed with HTTP {exc.code}"
                    ) from exc
            except (URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt >= retries:
                    raise OllamaTransportError("Ollama TRAINING request failed closed") from exc
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise OllamaTransportError("Ollama response was not JSON") from exc
            else:
                if not isinstance(parsed, dict):
                    raise OllamaTransportError("Ollama response was not an object")
                return parsed
            time.sleep(min(2 ** attempt, 16))
        raise OllamaTransportError("Ollama TRAINING request failed closed") from last_error

    return _send


def assistant_content(response: Mapping[str, Any]) -> str | None:
    """Return assistant content from chat or generate-shaped Ollama bodies."""
    message = response.get("message")
    if isinstance(message, Mapping) and isinstance(message.get("content"), str):
        return message["content"]
    if isinstance(response.get("response"), str):
        return response["response"]
    return None


def read_usage(
    response: Mapping[str, Any],
    *,
    payload: Mapping[str, Any] | None = None,
    content: str | None = None,
) -> tuple[int, int, str]:
    """Return ``(input_tokens, output_tokens, usage_source)``.

    Prefer Ollama's native eval counts. If they are absent, estimate from the
    conservative AAT byte/4 proxy and label the row as estimated.
    """
    prompt_tokens = response.get("prompt_eval_count")
    completion_tokens = response.get("eval_count")
    if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
        if prompt_tokens < 0 or completion_tokens < 0:
            raise OllamaTransportError("Ollama usage evidence is malformed")
        return prompt_tokens, completion_tokens, USAGE_REPORTED
    prompt_text = json.dumps(payload if payload is not None else {}, sort_keys=True, separators=(",", ":"))
    output_text = content if isinstance(content, str) else ""
    return (
        _byte_proxy_tokens(prompt_text),
        _byte_proxy_tokens(output_text),
        USAGE_ESTIMATED,
    )


def read_decision(
    response: Mapping[str, Any],
    *,
    model_id: str,
    turn: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    if response.get("model") not in (model_id, None) and not _model_matches(response.get("model"), model_id):
        return None, "MODEL_IDENTITY_DRIFT"
    if response.get("done") is False:
        return None, "RESPONSE_NOT_COMPLETED"
    content = assistant_content(response)
    done_reason = response.get("done_reason")
    finish_reason = None
    if isinstance(done_reason, str):
        finish_reason = done_reason
    if turn is not None:
        return parse_deliberation_turn(
            content or "",
            turn=turn,
            finish_reason=finish_reason,
            done_reason=done_reason if isinstance(done_reason, str) else None,
        )
    if not isinstance(content, str) or not content.strip():
        return None, "OUTPUT_TRUNCATED" if finish_reason in {"length", "max_tokens"} else "Actor output is not JSON"
    try:
        decision = json.loads(_json_text(content))
    except json.JSONDecodeError:
        return None, "OUTPUT_TRUNCATED" if finish_reason in {"length", "max_tokens"} else "Actor output is not JSON"
    if not isinstance(decision, Mapping) or set(decision) != set(ACTOR_DECISION_KEYS):
        return None, "Actor output schema mismatch"
    if decision["action"] not in LEGAL_ACTIONS:
        return None, "Actor action is not allowed"
    if (
        not isinstance(decision["confidence"], (int, float))
        or isinstance(decision["confidence"], bool)
        or not 0 <= float(decision["confidence"]) <= 1
    ):
        return None, "Actor confidence is invalid"
    if not all(
        isinstance(decision[key], str) and decision[key]
        for key in ("horizon", "invalidation", "rationale")
    ):
        return None, "Actor text fields are invalid"
    return {
        "action": decision["action"],
        "confidence": float(decision["confidence"]),
        "horizon": decision["horizon"],
        "invalidation": decision["invalidation"],
        "rationale": decision["rationale"],
    }, None


def payload_turn(payload: Mapping[str, Any]) -> str | None:
    messages = payload.get("messages")
    if not isinstance(messages, list) or len(messages) < 2:
        return None
    user = messages[1]
    if not isinstance(user, Mapping) or not isinstance(user.get("content"), str):
        return None
    try:
        body = json.loads(user["content"])
    except json.JSONDecodeError:
        return None
    turn = body.get("turn") if isinstance(body, Mapping) else None
    if turn in DELIBERATION_TURN_ROLES:
        return turn
    return None


def request_hash(payload: Mapping[str, Any]) -> str:
    return canonical_hash(payload)


def reject_snippet(response: Mapping[str, Any]) -> str | None:
    return raw_content_snippet(assistant_content(response))


def _format_hostport(hostname: str, port: int | None) -> str:
    if ":" in hostname and "." not in hostname:
        host = f"[{hostname}]"
    else:
        host = hostname
    if port is None:
        return host
    return f"{host}:{port}"


def _model_matches(returned: Any, expected: str) -> bool:
    if not isinstance(returned, str):
        return False
    if returned == expected:
        return True
    # Ollama sometimes echoes the tag without a registry prefix, or with one.
    return returned.split("/")[-1] == expected.split("/")[-1]


def _byte_proxy_tokens(text: str) -> int:
    encoded = text.encode("utf-8")
    return max(1, len(encoded) // BYTES_PER_TOKEN_PROXY) if encoded else 1


def _json_text(content: str) -> str:
    text = content.strip()
    if not text.startswith("```"):
        return text
    text = text[3:]
    if text[:4].lower() == "json":
        text = text[4:]
    text = text.strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return text
