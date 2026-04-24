QBot Log RAG Diagnostic System

This project builds a real-time diagnostic assistant for a robot (QBot) using Retrieval-Augmented Generation (RAG) combined with rule-based and graph-based reasoning.

Features
Live ROS2 topic monitoring (QBot runtime)
Topic health → structured diagnostic logs
Lightweight embedding-based retrieval (edge-compatible, no FAISS)
Rule-based diagnosis engine
Graph-based reasoning for cause-effect explanation
Example

User query:

Why is the robot not moving?

Output:

Detects zero speed feedback
Identifies that robot is not moving

Explains dependency chain:

joystick → teleop → /cmd_vel → driver → feedback → movement
Suggests debugging steps
Tech Stack
Python
SentenceTransformers
Scikit-learn (cosine similarity for edge retrieval)
ROS2 (QBot runtime)
Rule-based + Graph reasoning
Running on QBot
1. Start QBot runtime
~/ENGR857_Narayan_Shivangi/start_qbot.sh
2. Activate project environment
cd ~/ENGR857_Narayan_Shivangi/project/qbot-log-rag
source shivangi/bin/activate
3. Collect live topic health
python src/topic_health_collector.py

This records real-time robot state into:

data/processed/live_topic_health.jsonl
4. Convert topic health into logs
python src/health_to_logs.py

This generates:

data/processed/converted_logs.jsonl
5. Run diagnostic assistant
python src/diagnose.py

Example query:

why is the robot not moving
System Pipeline
ROS2 Topics
→ Topic Health Collector
→ Structured Logs
→ Embeddings (SentenceTransformers)
→ Retrieval (Cosine Similarity)
→ Rule-based Diagnosis
→ Graph-based Explanation
Next Steps
Real-time streaming diagnosis (no manual conversion step)
Integrate LLM for natural explanations
Expand diagnostic graph (multi-failure reasoning)
Deploy as UI (Streamlit / web dashboard)
Important Fixes I Made
Removed FAISS dependency on QBot (ARM-compatible pipeline)
Switched to live ROS2 topic-based diagnostics
Added structured health → log transformation