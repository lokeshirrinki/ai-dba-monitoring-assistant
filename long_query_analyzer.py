def classify_long_running_query(query):
    wait_event = query.get("wait_event")
    wait_type = query.get("wait_event_type")

    if wait_event == "PgSleep":
        return {
            "severity": "INFO",
            "diagnosis": "Query is waiting on pg_sleep",
            "recommendation": "Verify whether the sleep is intentional."
        }

    if wait_type == "Lock":
        return {
            "severity": "WARNING",
            "diagnosis": "Long-running query waiting on a lock",
            "recommendation": "Investigate blocking sessions."
        }

    return {
        "severity": "WARNING",
        "diagnosis": "Long-running active query detected",
        "recommendation": "Investigate execution time and wait events."
    }
