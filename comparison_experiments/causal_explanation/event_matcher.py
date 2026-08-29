#!/usr/bin/env python3
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
COMPARISON_ROOT = HERE.parents[1]
if str(COMPARISON_ROOT) not in sys.path:
    sys.path.insert(0, str(COMPARISON_ROOT))

from common.embedding_client import embed, cosine
from causal_explanation.causal_events import CAUSAL_EVENTS

_EVENT_VECTOR_CACHE = None


def _build_event_vector_cache():
    global _EVENT_VECTOR_CACHE
    if _EVENT_VECTOR_CACHE is not None:
        return _EVENT_VECTOR_CACHE

    cache = {}
    for event_name, definition in CAUSAL_EVENTS.items():
        exemplars = [
            definition.get("event_label", event_name),
            definition.get("effect", ""),
            *definition.get("question_examples", []),
        ]
        exemplars = [
            text.strip()
            for text in exemplars
            if isinstance(text, str) and text.strip()
        ]
        cache[event_name] = [
            {"text": text, "embedding": embed(text)}
            for text in exemplars
        ]

    _EVENT_VECTOR_CACHE = cache
    return cache


def match_question(question, top_k=3):
    """
    Map a natural-language question to a predefined causal event.

    Each example utterance is embedded separately. The event score is the
    strongest similarity to any exemplar for that event. This is closer in
    spirit to intent recognition from multiple training utterances than
    embedding all examples as one concatenated document.
    """
    q = embed(question)
    cache = _build_event_vector_cache()
    results = []

    for event_name, exemplars in cache.items():
        scored = [
            {"text": item["text"], "score": cosine(q, item["embedding"])}
            for item in exemplars
        ]
        scored.sort(key=lambda item: item["score"], reverse=True)
        best = scored[0]
        results.append({
            "event_name": event_name,
            "score": best["score"],
            "matched_example": best["text"],
            "definition": CAUSAL_EVENTS[event_name],
        })

    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:max(1, int(top_k))]
