from llama_cpp import Llama

MODEL_PATH = "/home/nvidia/ENGR857_Narayan_Shivangi/project/llm_model/qwen.gguf"

llm = Llama(
    model_path=MODEL_PATH,
    n_ctx=1024,
    n_threads=4,
    verbose=False
)

def explain(text):
    prompt = f"""
You are a robot diagnostic assistant.

Explain clearly and simply.

{text}

Answer:
"""

    output = llm(
        prompt,
        max_tokens=60,
        temperature=0.2
    )

    return output["choices"][0]["text"].strip()
