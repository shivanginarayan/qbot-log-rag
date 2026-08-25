# QBot Chat UI

This is a separate browser UI for the existing QBot log-RAG command. It does
not modify or replace the map-labeler, navigation UI, or `ask_robot.py`.

It uses the existing RAG pipeline and a small local BGE-M3 compatibility
service. The compatibility service avoids requiring a separate Ollama install.

## One-time Python setup

The QBot uses a custom NVIDIA PyTorch build. Install the pinned packages with
`--no-deps` so pip does not replace PyTorch, NumPy, SciPy, or ROS packages:

```bash
cd ~/ENGR857_Narayan_Shivangi/project/qbot-log-rag
python3 -m pip install --user --no-deps \
  sentence-transformers==3.2.1 \
  transformers==4.46.3 \
  huggingface-hub==0.36.2 \
  hf-xet==1.4.3 \
  tokenizers==0.20.3 \
  safetensors==0.5.3 \
  regex==2024.11.6
```

Do not run an unpinned `pip install -r requirements.txt` on the QBot.

## Start

```bash
cd ~/ENGR857_Narayan_Shivangi/project/qbot-log-rag
export NVIDIA_API_KEY="your-key"
./run_qbot_chat_ui.sh
```

On the first run, the launcher downloads `BAAI/bge-m3` and caches it under
`runtime_logs/huggingface`. Later runs reuse that local cache. The launcher
starts the compatibility endpoint on `127.0.0.1:11434`, verifies an embedding,
and then starts the chat UI.

Open `http://ROBOT_IP:8766`. The existing map-labeler can continue running on
port `8765`.

The chat UI requires the same RAG indexes as `src/reasoning/ask_robot.py`.

## Stored chat data

Each submitted chat request is stored in:

```text
runtime_logs/private_chat/qbot_chat_history.xlsx
runtime_logs/private_chat/qbot_chat_history.jsonl
```

The workbook records the user name, question, response, model, answer style,
selected map, status, retrieval count, response time, and error details. The
JSONL file is an append-only backup used to rebuild the workbook safely.

These files are developer-only records. They are not served by the public chat
website and there is no user download endpoint. A developer with shell access
to the QBot can inspect or copy them directly from `runtime_logs/private_chat`.
The directory is created with owner-only permissions (`700`) and the files use
owner-only permissions (`600`). Users sharing the same `nvidia` login still
have the same filesystem access as the developer.

## Optional settings

```bash
QBOT_CHAT_HOST=0.0.0.0
QBOT_CHAT_PORT=8766
QBOT_CHAT_LOG_FILE=/path/to/chat_history.xlsx
```
