"""
Thin wrapper around Qwen-Max for schema-enforced agent calls.

Qwen Cloud (DashScope) exposes an OpenAI-compatible endpoint, so we use the
`openai` SDK pointed at Qwen's base_url rather than a bespoke HTTP client —
this keeps the call site boring and lets you swap models via config alone.

Structured output: we ask for JSON mode via response_format and additionally
put the target schema in the prompt explicitly, since not every
OpenAI-compatible provider enforces response_format as strictly as OpenAI
itself does. Every response is validated against the Pydantic model before
being trusted; a validation failure triggers exactly one retry with an
explicit correction message (SPEC.md §9, point 3), and a second failure
raises rather than silently returning malformed data.
"""

from __future__ import annotations

import json
import time
from typing import TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.config import settings

T = TypeVar("T", bound=BaseModel)

_client = AsyncOpenAI(api_key=settings.qwen_api_key, base_url=settings.qwen_base_url)


class SchemaValidationFailure(Exception):
    pass


async def call_agent(
    *,
    system_prompt: str,
    user_content: str,
    output_schema: type[T],
    temperature: float | None = None,
) -> tuple[T, int]:
    """
    Calls Qwen-Max with a system prompt + user content, enforces JSON output
    matching `output_schema`, and returns (parsed_model, latency_ms).
    """
    schema_hint = json.dumps(output_schema.model_json_schema(), indent=2)
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"{user_content}\n\n"
                "Respond with ONLY a JSON object matching this schema, no "
                f"prose before or after it:\n{schema_hint}"
            ),
        },
    ]

    start = time.monotonic()
    parsed, error, raw = await _attempt(messages, output_schema, temperature)

    if parsed is None:
        # One correction retry, per SPEC.md §9.
        messages.append({"role": "assistant", "content": raw or ""})
        messages.append(
            {
                "role": "user",
                "content": (
                    "Your last output didn't match the required schema "
                    f"({error}). Respond again with ONLY valid JSON matching "
                    "the schema given earlier. Ensure the JSON is complete and not truncated."
                ),
            }
        )
        parsed, error, _ = await _attempt(messages, output_schema, temperature)

    latency_ms = int((time.monotonic() - start) * 1000)

    if parsed is None:
        raise SchemaValidationFailure(f"Agent output failed schema validation twice: {error}")

    return parsed, latency_ms


async def _attempt(
    messages: list[dict], output_schema: type[T], temperature: float | None
) -> tuple[T | None, str | None, str]:
    raw = ""
    try:
        response = await _client.chat.completions.create(
            model=settings.qwen_model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature if temperature is not None else settings.agent_temperature,
            max_tokens=3000,
        )
        raw = response.choices[0].message.content or ""
        
        if response.choices[0].finish_reason == "length":
            return None, "Output truncated (hit max_tokens). The model may be looping.", raw
            
        # Strip markdown JSON wrappers if present
        clean_raw = raw.strip()
        if clean_raw.startswith("```json"):
            clean_raw = clean_raw[7:]
        elif clean_raw.startswith("```"):
            clean_raw = clean_raw[3:]
        if clean_raw.endswith("```"):
            clean_raw = clean_raw[:-3]
        clean_raw = clean_raw.strip()
            
        data = json.loads(clean_raw)
        return output_schema.model_validate(data), None, raw
    except (json.JSONDecodeError, ValidationError) as exc:
        return None, str(exc), raw
    except Exception as exc:  # noqa: BLE001 — surface upstream API errors distinctly
        return None, f"API error: {exc}", raw


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Used only by conflict_detection.topic_similarity_embeddings if you
    swap in embedding-based topic matching — not on the default critical path."""
    response = await _client.embeddings.create(model=settings.qwen_embedding_model, input=texts)
    return [item.embedding for item in response.data]
