#!/usr/bin/env python3

import json
import math
import urllib.error
import urllib.request


MODEL_EMBED = "bge-m3"

NEW_URL = "http://localhost:11434/api/embed"
OLD_URL = "http://localhost:11434/api/embeddings"

# Keep each embedding request comfortably below the model/server
# context limit. Long ROS log records are embedded as multiple chunks
# and pooled into one record embedding.
MAX_CHARS_PER_CHUNK = 6000


def normalize(vector):
    norm = math.sqrt(
        sum(value * value for value in vector)
    )

    if norm == 0:
        return vector

    return [
        value / norm
        for value in vector
    ]


def cosine(a, b):
    return sum(
        x * y
        for x, y in zip(a, b)
    )


def _post_json(url, payload):
    body = json.dumps(
        payload
    ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json"
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=120,
    ) as response:
        return json.loads(
            response
            .read()
            .decode("utf-8")
        )


def _embed_one(text):
    """
    Embed one bounded-size text chunk.

    Try the newer Ollama endpoint first, then fall back to the
    older endpoint used by this QBot installation.
    """
    try:
        data = _post_json(
            NEW_URL,
            {
                "model": MODEL_EMBED,
                "input": text,
            },
        )

        embeddings = data.get(
            "embeddings"
        )

        if (
            embeddings
            and isinstance(
                embeddings,
                list,
            )
        ):
            return normalize(
                embeddings[0]
            )

    except Exception:
        pass

    data = _post_json(
        OLD_URL,
        {
            "model": MODEL_EMBED,
            "prompt": text,
        },
    )

    embedding = data.get(
        "embedding"
    )

    if not embedding:
        raise RuntimeError(
            "Ollama returned no embedding."
        )

    return normalize(
        embedding
    )


def _chunk_text(text):
    text = str(text)

    if not text:
        return [""]

    return [
        text[i:i + MAX_CHARS_PER_CHUNK]
        for i in range(
            0,
            len(text),
            MAX_CHARS_PER_CHUNK,
        )
    ]


def _mean_pool(vectors):
    if not vectors:
        raise RuntimeError(
            "No vectors were produced."
        )

    if len(vectors) == 1:
        return vectors[0]

    width = len(vectors[0])

    pooled = [
        sum(
            vector[i]
            for vector in vectors
        )
        / len(vectors)
        for i in range(width)
    ]

    return normalize(
        pooled
    )


def embed(text):
    """
    Embed arbitrary-length text.

    Short text: one embedding request.
    Long text: split into bounded chunks, embed each chunk, and
    mean-pool the chunk vectors into one record embedding.
    """
    chunks = _chunk_text(
        text
    )

    vectors = [
        _embed_one(chunk)
        for chunk in chunks
    ]

    return _mean_pool(
        vectors
    )
