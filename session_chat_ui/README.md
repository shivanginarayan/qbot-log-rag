# QBot Session Chat UI

This folder contains the standalone replacement chat UI. It does not import,
change, or depend on the project's earlier chat UI files.

The UI performs the same core RAG call as the terminal loop in
`run_full_log_experiment.sh`:

```text
python src/reasoning/ask_robot.py \
  --session-id SESSION_ID \
  --audience user \
  --question "USER QUESTION"
```

It finds the newest running experiment session automatically. Each request is
inserted into that session's `runtime_logs/session_SESSION_ID/robot.db` before
the LLM is called. The same row is then updated with the robot response shown
on the page.

## Start the UI

First, run the team experiment normally in one terminal:

```bash
cd ~/ENGR857_Narayan_Shivangi/project/qbot-log-rag
./run_full_log_experiment.sh
```

In a second terminal, start this UI:

```bash
cd ~/ENGR857_Narayan_Shivangi/project/qbot-log-rag
./session_chat_ui/run_ui.sh
```

If `NVIDIA_API_KEY` is not already exported in the second terminal, the
launcher asks for it with hidden input. The key is kept only in the UI server
process environment and is not written to the database or browser.

Open this address on the QBot or another computer on its network:

```text
http://ROBOT_IP:8766
```

The existing map-labeler uses port 8765, so both interfaces can run together.

No new packages are required by the UI server. It uses the Python 3.8 standard
library. The unchanged `ask_robot.py` pipeline still requires `requests`, which
is already part of the project environment.

## Database record

The UI creates one additive table inside the selected session database:

```text
ui_chat_interactions
```

Important columns are:

- `session_id`
- `user_id`
- `question`
- `robot_response`
- `status`
- `audience`
- `asked_at_iso` and `answered_at_iso`
- `model`, retrieval count, response time, and error details

To inspect the stored exchanges after a session:

```bash
sqlite3 runtime_logs/session_SESSION_ID/robot.db \
  "SELECT user_id, question, robot_response FROM ui_chat_interactions;"
```

The UI does not provide a public database download route.

## Options

Use a different network interface or port:

```bash
./session_chat_ui/run_ui.sh --host 127.0.0.1 --port 9000
```

Pin the UI to one known session instead of auto-detecting the latest running
session:

```bash
./session_chat_ui/run_ui.sh --session-id 20260824_120000_ab12
```

## Run the isolated tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s session_chat_ui/tests -v
```
