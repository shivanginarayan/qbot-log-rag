import json
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

model = SentenceTransformer("all-MiniLM-L6-v2")


def load_logs(file_path):
    logs = []
    with open(file_path, "r") as f:
        for line in f:
            log = json.loads(line)
            logs.append(
                f"Time: {log['timestamp']}. "
                f"Topic: {log['topic']}. "
                f"Severity: {log['severity']}. "
                f"Message: {log['message']}"
            )
    return logs


log_texts = load_logs("data/processed/converted_logs.jsonl")
log_embeddings = model.encode(log_texts)


def search(query, k=2):
    query_embedding = model.encode([query])
    similarities = cosine_similarity(query_embedding, log_embeddings)[0]

    top_k_indices = similarities.argsort()[-k:][::-1]

    results = [log_texts[i] for i in top_k_indices]
    return results