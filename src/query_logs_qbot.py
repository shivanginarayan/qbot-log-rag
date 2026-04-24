import json
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

# Load model
model = SentenceTransformer("all-MiniLM-L6-v2")

# Load logs
with open("vectorstore/log_texts.json", "r") as f:
    log_texts = json.load(f)

# Precompute embeddings
log_embeddings = model.encode(log_texts)


def search(query, k=2):
    query_embedding = model.encode([query])
    similarities = cosine_similarity(query_embedding, log_embeddings)[0]

    top_k_indices = similarities.argsort()[-k:][::-1]

    results = [log_texts[i] for i in top_k_indices]
    return results
