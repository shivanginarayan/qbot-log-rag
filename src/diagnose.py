from query_logs import search
from rule_diagnoser import apply_rules
from diagnostic_graph import explain_graph_path


def infer_issue_key(user_query):
    query = user_query.lower()

    if "move" in query or "moving" in query or "not moving" in query:
        return "robot_not_moving"

    if "lidar" in query or "scan" in query:
        return "lidar_issue"

    if "battery" in query or "power" in query:
        return "battery_issue"

    return "unknown"


def diagnose_issue(user_query):
    logs = search(user_query, k=2)
    findings = apply_rules(logs)
    issue_key = infer_issue_key(user_query)
    graph_reasoning = explain_graph_path(issue_key)

    response = []
    response.append(f"User question:\n{user_query}\n")

    response.append("Relevant QBot logs:")
    for log in logs:
        response.append(f"- {log}")

    response.append("\nDiagnosis:")

    for i, finding in enumerate(findings, start=1):
        response.append(f"\n{i}. Issue: {finding['issue']}")
        response.append(f"   Cause: {finding['cause']}")
        response.append(f"   Suggested action: {finding['action']}")

    response.append("\n" + graph_reasoning)

    return "\n".join(response)


if __name__ == "__main__":
    while True:
        query = input("\nAsk about QBot issue (type 'exit' to quit): ")

        if query.lower() == "exit":
            break

        print(diagnose_issue(query))