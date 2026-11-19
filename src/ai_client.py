# -*- coding: utf-8 -*-
"""
Cliente IA unificado (Google Gemini API) para resúmenes ejecutivos opcionales.
Portado con las mejoras de Agente Finanzas:
- Autenticación mediante cabecera `x-goog-api-key`.
- Cadena automática de modelos de reserva (`gemini-flash-lite-latest` -> `gemini-flash-latest` -> `gemini-2.5-flash`).
- Reintentos con espera progresiva ante HTTP 429 / 503.
- Filtrado seguro de bloques `thought` en modelos con razonamiento.
"""

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Sequence

DEFAULT_GEMINI_MODELS = (
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-2.5-flash",
)


def _dedupe_models(models: Sequence[Optional[str]]) -> List[str]:
    out: List[str] = []
    for m in models:
        if m and m not in out:
            out.append(m)
    return out


def call_gemini(
    prompt: str,
    *,
    api_key: Optional[str] = None,
    system_instruction: Optional[str] = None,
    preferred_model: Optional[str] = None,
    fallback_models: Optional[Sequence[str]] = None,
    json_out: bool = False,
    temperature: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
    timeout: int = 45,
    max_retries: int = 2,
) -> Optional[str]:
    key = (api_key or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        return None

    models = _dedupe_models(
        [preferred_model] + list(fallback_models or DEFAULT_GEMINI_MODELS)
    )

    body: Dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
    }
    if system_instruction:
        body["system_instruction"] = {"parts": [{"text": system_instruction}]}

    gen_cfg: Dict[str, Any] = {}
    if json_out:
        gen_cfg["responseMimeType"] = "application/json"
    if temperature is not None:
        gen_cfg["temperature"] = temperature
    if max_output_tokens is not None:
        gen_cfg["maxOutputTokens"] = max_output_tokens
    if gen_cfg:
        body["generationConfig"] = gen_cfg

    payload_bytes = json.dumps(body).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": key,
    }

    for modelo in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
        for intento in range(max_retries):
            try:
                req = urllib.request.Request(
                    url, data=payload_bytes, headers=headers, method="POST"
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8", errors="replace"))
                candidates = data.get("candidates") or []
                if not candidates:
                    break
                parts = candidates[0].get("content", {}).get("parts") or []
                text = "".join(
                    p.get("text", "") for p in parts if not p.get("thought")
                ).strip()
                if text:
                    return text
                break
            except urllib.error.HTTPError as e:
                if e.code in (400, 404):
                    break
                if e.code in (401, 403):
                    return None
                if intento + 1 < max_retries:
                    time.sleep(2 + 3 * intento)
            except Exception:
                break
    return None
