import faiss
import json
import numpy as np
from sentence_transformers import SentenceTransformer

# Load model
model = SentenceTransformer("all-MiniLM-L6-v2")

# Load index
index = faiss.read_index("vectorstore/qbot_index.faiss")

# Load text mapping
with open("vectorstore/log_texts.json", "r") as f:
    log_texts = json.load(f)


def search(query, k=3):
    query_embedding = model.encode([query])
    distances, indices = index.search(np.array(query_embedding), k)

    results = []
    for idx in indices[0]:
        results.append(log_texts[idx])

    return results


if __name__ == "__main__":
    while True:
        query = input("\nAsk about QBot issue (type 'exit' to quit): ")

        if query.lower() == "exit":
            break

        results = search(query)

        print("\nTop relevant logs:\n")
        for r in results:
            print(r)
            print("-" * 50)