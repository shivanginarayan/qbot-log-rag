# QBot Comparison Experiments

This folder contains only comparison systems. It does not modify the
proposed QBot explanation system.

## A. Explaining-Autonomy-style /rosout RAG baseline

Pipeline:

```text
/rosout textual logs
-> collapse immediately repeated identical log messages
-> BGE-M3 embeddings
-> semantic top-k retrieval
-> Nemotron
-> answer
```

This baseline does NOT use the proposed system's structured query,
task lifecycle, task-intent memory, map/global behavior memory, or
evidence-packet logic.

The session rosbag must contain `/rosout`. If it does not, this
baseline stops instead of substituting raw sensor topics.

Build index:

```bash
./comparison_experiments/run_comparison.sh rosout-build \
    --session-id latest
```

Inspect retrieval:

```bash
./comparison_experiments/run_comparison.sh rosout \
    --session-id latest \
    --question "Why did localization fail?" \
    --show-retrieval \
    --no-llm
```

Ask:

```bash
./comparison_experiments/run_comparison.sh rosout \
    --session-id latest \
    --question "Why did localization fail?"
```

## B. Adapted causal / temporal-counterfactual baseline

Pipeline:

```text
task_events
-> fixed request/start/finish model
-> explicit causal-log entries
-> local counterfactual statements
-> role-specific verbalization
-> Nemotron
```

This is an adapted navigation-domain comparison baseline, not an exact
reproduction of either causal-explanation paper.

Inspect:

```bash
./comparison_experiments/run_comparison.sh causal \
    --session-id latest \
    --question "Why did localization fail?" \
    --role engineer \
    --show-model \
    --no-llm
```

Ask as user:

```bash
./comparison_experiments/run_comparison.sh causal \
    --session-id latest \
    --question "Why did localization fail?" \
    --role user
```

Ask as engineer:

```bash
./comparison_experiments/run_comparison.sh causal \
    --session-id latest \
    --question "Why did localization fail?" \
    --role engineer
```

## Replace old folder

From repo root:

```bash
rm -rf comparison_experiments
```

Copy/extract this folder into the repo root, then:

```bash
chmod +x \
    comparison_experiments/run_comparison.sh \
    comparison_experiments/explaining_autonomy/run.sh \
    comparison_experiments/causal_counterfactual/run.sh
```

Compile:

```bash
python -m py_compile \
    comparison_experiments/common/nvidia_client.py \
    comparison_experiments/common/session_utils.py \
    comparison_experiments/common/embedding_client.py \
    comparison_experiments/explaining_autonomy/rosout_reader.py \
    comparison_experiments/explaining_autonomy/build_rosout_index.py \
    comparison_experiments/explaining_autonomy/ask_rosout_rag.py \
    comparison_experiments/causal_counterfactual/causal_log.py \
    comparison_experiments/causal_counterfactual/ask_causal_counterfactual.py
```

Set:

```bash
export NVIDIA_API_KEY='...'
```

The /rosout RAG baseline also requires the local Ollama BGE-M3 service.

For fair evaluation, keep the robot session, user question, and Nemotron
model constant. Only the explanation architecture should change.
