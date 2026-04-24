\# QBot Log RAG Diagnostic System



This project builds a real-time diagnostic assistant for a robot (QBot) using Retrieval-Augmented Generation (RAG) and a diagnostic graph.



\## Features



\- Log ingestion (mock for now, real ROS2 logs later)

\- Vector search using FAISS

\- Rule-based diagnosis engine

\- Graph-based reasoning for cause-effect explanation



\## Example



User query:

> Why is the robot not moving?



Output:

\- Detects missing `/cmd\_vel`

\- Identifies teleop issue

\- Explains dependency chain

\- Suggests ROS2 debugging commands



\## Tech Stack



\- Python

\- SentenceTransformers

\- FAISS

\- Rule-based + Graph reasoning



\## Next Steps



\- Integrate real ROS2 logs

\- Add LLM-based explanation layer

\- Deploy on QBot (Jetson Orin Nano)

