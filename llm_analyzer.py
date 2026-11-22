
import json
from groq import Groq

MODEL = "openai/gpt-oss-20b"


def explain_incident(question, incident_data, analysis_type="blocking"):
    client = Groq(timeout=30.0, max_retries=0)

    if analysis_type == "blocking":
        safe_data = {
            "analysis_type": "blocking",
            "status": incident_data.get("status"),
            "incident_count": incident_data.get("incident_count"),
            "summary": incident_data.get("summary"),
            "findings": [
                {
                    "blocker_state": item.get("blocker_state"),
                    "wait_event": item.get("wait_event"),
                    "transaction_duration": item.get(
                        "transaction_duration"
                    ),
                    "diagnosis": item.get("diagnosis"),
                    "recommendation": item.get("recommendation"),
                }
                for item in incident_data.get("findings", [])
            ],
        }

    elif analysis_type == "long_running":
        safe_data = {
            "analysis_type": "long_running",
            "long_running_query_count": incident_data.get(
                "long_running_query_count"
            ),
            "findings": [
                {
                    "query_duration": item.get("query_duration"),
                    "wait_event_type": item.get("wait_event_type"),
                    "wait_event": item.get("wait_event"),
                    "severity": item.get("severity"),
                    "diagnosis": item.get("diagnosis"),
                    "recommendation": item.get("recommendation"),
                }
                for item in incident_data.get("findings", [])
            ],
        }

    else:
        raise ValueError("Unsupported analysis type")

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a PostgreSQL production DBA assistant. "
                    "Use only the supplied monitoring evidence. "
                    "Distinguish observations from possible causes. "
                    "Do not invent incidents or performance problems. "
                    "An active query exceeding 60 seconds is not "
                    "necessarily a performance incident. "
                    "PgSleep indicates an intentional sleep wait, "
                    "not evidence of CPU-intensive execution. "
                    "If no findings exist, report that no matching "
                    "issues were observed in the monitoring snapshot. "
                    "Recommend safe, read-only investigation first. "
                    "Never recommend automatic session termination, "
                    "commit, rollback, or other database changes. "
                    "Any remediation requires human approval. "
                    "Keep the explanation concise and practical."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"DBA question: {question}\n\n"
                    "Verified monitoring data:\n"
                    f"{json.dumps(safe_data, default=str)}"
                ),
            },
        ],
        max_completion_tokens=1000,
        reasoning_effort="low",
    )

    answer = response.choices[0].message.content

    if not answer:
        raise RuntimeError("The LLM returned an empty response.")

    return answer

