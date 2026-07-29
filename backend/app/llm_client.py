"""
llm_client.py — Client LLM unifié avec fallback Groq → OpenRouter.

Architecture :
  1. Essai via Groq (rapide). Modèle par défaut : llama-3.3-70b-versatile,
     mais chaque appel peut préciser un modèle différent (ex. un modèle
     plus léger pour les tâches de filtrage, afin de ménager le TPM).
  2. Si Groq échoue (rate limit, clé absente, erreur), fallback sur OpenRouter.
  3. Backoff sur rate limits pour chaque provider, basé sur le Retry-After
     réel renvoyé par l'API quand disponible, sinon backoff exponentiel.

Usage :
  from app.llm_client import llm_call, llm_call_json, GROQ_MODEL_FAST

  # Appel texte (generation.py)
  text = llm_call(system_prompt, user_prompt, label="chat")

  # Appel JSON avec modèle léger (filtrage de pertinence, ai_auditor.py)
  data = llm_call_json(system_prompt, user_prompt, label="filtrage", model=GROQ_MODEL_FAST)
"""

from __future__ import annotations

import json
import os
import time

from dotenv import load_dotenv

load_dotenv()

# ── Groq ──────────────────────────────────────────────────────────────
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# Modèle par défaut : bonne qualité de raisonnement, quota TPM serré (~6-12K/min
# sur le tier gratuit). À réserver aux tâches qui en ont vraiment besoin
# (analyse de conformité finale).
GROQ_MODEL_DEFAULT = "llama-3.3-70b-versatile"

# Modèle rapide/léger : quota bien plus généreux sur le tier gratuit
# (14 400 req/jour, 500K tokens/jour). À utiliser pour les tâches plus
# simples comme le filtrage de pertinence, qui n'ont pas besoin du
# raisonnement le plus poussé mais consomment beaucoup de tokens en entrée
# (plusieurs articles candidats par appel).
GROQ_MODEL_FAST = "llama-3.1-8b-instant"

# ── OpenRouter (fallback) ─────────────────────────────────────────────
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")
# NB : les slugs ":free" d'OpenRouter changent régulièrement de disponibilité.
# Vérifier sur https://openrouter.ai/models?max_price=0 avant de figer ce choix.
# Slug payant utilisé ici par défaut car le variant ":free" équivalent n'est
# plus servi (404 constaté en prod le 26/07/2026).
#OPENROUTER_MODEL = "nvidia/nemotron-nano-9b-v2:free"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "openai/gpt-oss-20b:free"

def _groq_client():
    if not GROQ_API_KEY:
        return None
    from groq import Groq
    return Groq(api_key=GROQ_API_KEY)


def _openrouter_client():
    if not OPENROUTER_KEY:
        return None
    # pyrefly: ignore [missing-import]
    from openai import OpenAI
    return OpenAI(
        api_key=OPENROUTER_KEY,
        base_url=OPENROUTER_BASE_URL,
    )


def _extract_retry_after(exc: Exception) -> float | None:
    """
    Tente de lire le délai d'attente réel renvoyé par l'API (header
    Retry-After ou équivalent) plutôt que de deviner un backoff arbitraire.
    Robuste à l'absence de cette info : retourne None si rien d'exploitable.
    """
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) if response is not None else None
    if not headers:
        return None
    for key in ("retry-after", "Retry-After", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        value = headers.get(key) if hasattr(headers, "get") else None
        if value:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None

MAX_BACKOFF_SECONDS = 30.0  # au-delà, on bascule vers l'autre provider plutôt que d'attendre

def _call_provider(client, model: str, messages: list, json_mode: bool, label: str, retries: int = 3):
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    for attempt in range(retries):
        try:
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""
        except Exception as exc:
            err_msg = str(exc)
            if "429" in err_msg or "rate_limit" in err_msg or "quota" in err_msg:
                retry_after = _extract_retry_after(exc)
                backoff = retry_after if retry_after is not None else 3.0 * (2 ** attempt)

                if backoff > MAX_BACKOFF_SECONDS:
                    print(f"[LLM] Rate limit {model} pour '{label}' : attente réelle de {backoff:.0f}s "
                          f"dépasse le seuil de {MAX_BACKOFF_SECONDS:.0f}s → bascule vers le provider suivant "
                          f"plutôt que d'attendre.")
                    raise RuntimeError(
                        f"Quota temporairement indisponible sur {model} (reset dans {backoff:.0f}s), "
                        f"bascule demandée"
                    )

                print(f"[LLM] Rate limit {model} pour '{label}', pause {backoff:.0f}s (essai {attempt + 1}/{retries})…")
                time.sleep(backoff)
            else:
                print(f"[LLM] Erreur {model} pour '{label}' : {exc}")
                raise
    raise RuntimeError(f"Rate limit persistant sur {model} après {retries} essais")


def llm_call(
    system_prompt: str,
    user_prompt: str,
    label: str = "llm",
    json_mode: bool = False,
    model: str | None = None,
) -> str | None:
    """
    Appel LLM texte avec fallback Groq → OpenRouter.
    `model` permet de choisir un modèle Groq spécifique pour cet appel
    (ex. GROQ_MODEL_FAST pour une tâche de filtrage). Si non précisé,
    GROQ_MODEL_DEFAULT est utilisé.
    Retourne le contenu texte de la réponse ou None si tout échoue.
    """
    groq_model = model or GROQ_MODEL_DEFAULT
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # 1. Essai Groq
    groq = _groq_client()
    if groq:
        try:
            result = _call_provider(groq, groq_model, messages, json_mode, label)
            return result
        except Exception as exc:
            print(f"[LLM] Groq échoué pour '{label}' ({exc}), tentative OpenRouter…")

    # 2. Fallback OpenRouter
    openrouter = _openrouter_client()
    if openrouter:
        try:
            result = _call_provider(openrouter, OPENROUTER_MODEL, messages, json_mode, label)
            print(f"[LLM] '{label}' servi par OpenRouter ({OPENROUTER_MODEL})")
            return result
        except Exception as exc:
            print(f"[LLM] OpenRouter aussi échoué pour '{label}' : {exc}")

    print(f"[LLM] ÉCHEC TOTAL pour '{label}' — aucun provider LLM disponible")
    return None


def _strip_json_fences(raw: str) -> str:
    """
    Nettoyage défensif : certains modèles/providers entourent parfois leur
    réponse JSON de balises markdown (```json ... ```) malgré json_mode=True.
    """
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    return cleaned


def llm_call_json(
    system_prompt: str,
    user_prompt: str,
    label: str = "llm_json",
    model: str | None = None,
) -> dict | None:
    """
    Appel LLM avec réponse JSON forcée + fallback Groq → OpenRouter.
    `model` : voir llm_call.
    Retourne le dict parsé ou None si l'appel ou le parsing échoue.
    """
    raw = llm_call(system_prompt, user_prompt, label=label, json_mode=True, model=model)
    if raw is None:
        return None
    cleaned = _strip_json_fences(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        print(f"[LLM] JSON invalide pour '{label}' : {exc}\nContenu brut : {raw[:500]}")
        return None