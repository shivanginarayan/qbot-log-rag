import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
from pathlib import Path
import json

# Load model
model = SentenceTransformer("all-MiniLM-L6-v2")


def load_logs(file_path):
    logs = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            logs.append(json.loads(line))
    return logs


def log_to_text(log):
    return (
        f"Time: {log['timestamp']}. "
        f"Node: {log['node']}. "
        f"Topic: {log['topic']}. "
        f"Severity: {log['severity']}. "
        f"Message: {log['message']}"
    )


if __name__ == "__main__":
    path = Path("data/processed/converted_logs.jsonl")
    logs = load_logs(path)

    texts = [log_to_text(log) for log in logs]

    print("Creating embeddings...")
    embeddings = model.encode(texts)

    dim = embeddings.shape[1]

    index = faiss.IndexFlatL2(dim)
    index.add(np.array(embeddings))

    # Save index
    faiss.write_index(index, "vectorstore/qbot_index.faiss")

    # Save mapping
    with open("vectorstore/log_texts.json", "w") as f:
        json.dump(texts, f, indent=2)

    print("Index built and saved!")