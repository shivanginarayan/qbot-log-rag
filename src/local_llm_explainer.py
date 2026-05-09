import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

MODEL_PATH = "/home/nvidia/ENGR857_Narayan_Shivangi/project/llm_model/qwen_hf"

tokenizer = AutoTokenizer.from_pretrained(
    MODEL_PATH,
    local_files_only=True
)

model = AutoModelForCausalLM.from_pretrained(
    MODEL_PATH,
    local_files_only=True,
    torch_dtype=torch.float32,
    device_map=None
)

model.eval()


def llm_explain(diagnostic_text):
    prompt = f"""
You are a robot diagnostic assistant for a QBot.

Rewrite the following diagnosis in simple, clear language.
Do not invent new causes.
Only explain what the provided evidence says.

Diagnosis evidence:
{diagnostic_text}

Simple explanation:
"""

    inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=1024)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=40,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )

    decoded = tokenizer.decode(outputs[0], skip_special_tokens=True)

    if "Simple explanation:" in decoded:
        return decoded.split("Simple explanation:")[-1].strip()

    return decoded.strip()
