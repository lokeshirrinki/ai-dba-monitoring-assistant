
def analyze_blocking(data):
    incidents = data.get("blocking_sessions", [])

    if not incidents:
        return {
            "status": "healthy",
            "incident_count": 0,
            "summary": "No blocking sessions detected.",
            "recommendations": []
        }

    findings = []

    for incident in incidents:
        blocker_pid = incident["blocker_pid"]
        blocked_pid = incident["blocked_pid"]
        blocker_state = incident["blocker_state"]

        if blocker_state == "idle in transaction":
            diagnosis = (
                "The blocking session has an open transaction "
                "and is currently idle. It may be holding locks "
                "from earlier uncommitted statements."
            )
        else:
            diagnosis = (
                "The blocking session is preventing another "
                "session from acquiring a required lock."
            )

        findings.append({
            "blocked_pid": blocked_pid,
            "blocker_pid": blocker_pid,
            "blocker_state": blocker_state,
            "wait_event": incident["wait_event"],
            "transaction_duration":
                incident["blocker_transaction_duration"],
            "diagnosis": diagnosis,
            "recommendation": (
                "Contact the transaction owner and investigate "
                "the open transaction. Request a commit or "
                "rollback if appropriate. Do not terminate "
                "sessions automatically."
            )
        })

    return {
        "status": "blocking_detected",
        "incident_count": len(findings),
        "summary": f"Detected {len(findings)} blocking relationship(s).",
        "findings": findings,
        "requires_human_approval": True
    }
