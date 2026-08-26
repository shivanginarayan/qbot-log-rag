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

The browser begins with a User ID login page. It then presents the 23
demographic questions one at a time. The first three collect birth year,
gender, and engineering background. Questions 4 through 23 accept only a
numeric response from 1 (strongly disagree) through 5 (strongly agree). Each
answer is stored immediately in the current experiment database under that
User ID, so logging in again resumes the first unanswered question.

After the survey is complete, the existing chat interface opens without
asking for the User ID again. A returning participant who has already
completed the survey for the current experiment goes directly to chat. The UI
reads that user's recent saved conversations from the existing session
databases and displays them in chronological order. This history lookup is
read-only and does not copy or move the saved records.

## Start everything with one command

Run the team launcher normally:

```bash
cd ~/ENGR857_Narayan_Shivangi/project/qbot-log-rag
./run_full_log_experiment.sh
```

It now starts the map-labeler, evidence logging, robot workflow, and this RAG
chat UI together. No second terminal or second launch command is needed.

On the QBot computer, open:

```text
http://localhost:8766
```

Log in and complete the participant survey, then enter the NVIDIA API key in
the chat page's password field. The key is held only in the UI server's memory
and is passed temporarily to `ask_robot.py` while a question is answered. The
application does not write it to `robot.db`, a file, browser storage, or its
logs. It disappears when the launcher stops, and the UI also provides a
**Remove** button that clears it from server memory immediately.

Because the UI uses plain local HTTP, API-key entry is intentionally accepted
only from `localhost` on the QBot. After the key has been entered there, other
computers on the same network can use the chat at:

```text
http://ROBOT_IP:8766
```

The existing map-labeler uses port 8765, so both interfaces can run together.

The chat remains available while AMCL or Cartographer navigation is running.
The UI launches the unchanged team RAG module through `rag_compat.py`, which
supplies map-metadata helpers only if they are missing from that module. This
avoids the navigation-time map lookup crash without editing the team's RAG or
navigation files. The Map field follows the active map-labeler state and falls
back to maps created or recorded during the current experiment.

New maps are assigned to the User ID currently entered in the chat UI. The
assignment is stored in the additive `ui_user_maps` table and is never moved to
another user automatically. Switching User IDs changes the Map field to that
user's most recently assigned map; an ID with no maps sees "No maps for this
user." Enter the intended User ID before starting a new map in the map UI.

The standalone `./session_chat_ui/run_ui.sh` command remains available for
development, but it is not needed for the normal experiment.

No new packages are required by the UI server. It uses the Python 3.8 standard
library. The unchanged `ask_robot.py` pipeline still requires `requests`, which
is already part of the project environment.

## Database record

The UI creates four additive tables inside the selected session database:

```text
ui_chat_interactions
ui_user_maps
ui_participants
ui_demographic_responses
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

`ui_user_maps` stores only the session ID, map name, owning User ID, and the
time that ownership was first detected.

`ui_participants` records the User ID login and survey completion time for the
experiment. `ui_demographic_responses` stores the User ID, exact question,
answer, answer type, and answer time. The numeric agreement answers are stored
as the strings `1` through `5`.

To inspect the stored exchanges after a session:

```bash
sqlite3 runtime_logs/session_SESSION_ID/robot.db \
  "SELECT user_id, question, robot_response FROM ui_chat_interactions;"
```

To inspect the demographic responses:

```bash
sqlite3 runtime_logs/session_SESSION_ID/robot.db \
  "SELECT user_id, question_text, response_value FROM ui_demographic_responses ORDER BY user_id, question_index;"
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
