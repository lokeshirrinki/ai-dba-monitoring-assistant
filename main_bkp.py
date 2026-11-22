from incident_analyzer import analyze_blocking
import os
from long_query_analyzer import classify_long_running_query
from pydantic import BaseModel, Field
from llm_analyzer import explain_incident

import psycopg
from fastapi import FastAPI, HTTPException
from psycopg.rows import dict_row

app = FastAPI(
    title="AI DBA Monitoring API",
    version="0.1.0"
)

def get_db_connection():
    return psycopg.connect(
        host="localhost",
        port=5432,
        dbname="ai_dba_lab",
        user="ai_monitor",
        password=os.environ["DB_PASSWORD"],
        connect_timeout=5,
        options="-c default_transaction_read_only=on",
        row_factory=dict_row
    )

@app.get("/health")
def database_health():
    try:
        with psycopg.connect(
            host="localhost",
            port=5432,
            dbname="ai_dba_lab",
            user="ai_monitor",
            password=os.environ["DB_PASSWORD"],
            connect_timeout=5,
            options="-c default_transaction_read_only=on",
            row_factory=dict_row
        ) as connection:

            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT current_database() AS database,
                           current_user AS monitoring_user,
                           pg_size_pretty(
                               pg_database_size(current_database())
                           ) AS database_size,
                           now() - pg_postmaster_start_time()
                               AS server_uptime;
                """)
                database_info = cursor.fetchone()

                cursor.execute("""
                    SELECT COUNT(*) FILTER (
                               WHERE state = 'active'
                           ) AS active_sessions,
                           COUNT(*) FILTER (
                               WHERE state = 'idle'
                           ) AS idle_sessions,
                           COUNT(*) AS total_sessions
                    FROM pg_stat_activity
                    WHERE datname = current_database()
                      AND pid <> pg_backend_pid();
                """)
                session_info = cursor.fetchone()

                cursor.execute("""
                    SELECT pid AS blocked_pid,
                           pg_blocking_pids(pid) AS blocker_pids,
                           wait_event_type,
                           wait_event
                    FROM pg_stat_activity
                    WHERE datname = current_database()
                      AND cardinality(pg_blocking_pids(pid)) > 0;
                """)
                blocking_info = cursor.fetchall()

                return {
                    "status": "connected",
                    "database_info": {
                        **database_info,
                        "server_uptime": str(
                            database_info["server_uptime"]
                        )
                    },
                    "session_statistics": session_info,
                    "blocking_sessions": blocking_info,
                    "blocked_session_count": len(blocking_info)
                }

    except (psycopg.Error, KeyError) as error:
        raise HTTPException(
            status_code=503,
            detail="Database monitoring unavailable"
        ) from error


@app.get("/blocking-sessions")
def blocking_sessions():
    try:
        with psycopg.connect(
            host="localhost",
            port=5432,
            dbname="ai_dba_lab",
            user="ai_monitor",
            password=os.environ["DB_PASSWORD"],
            connect_timeout=5,
            options="-c default_transaction_read_only=on",
            row_factory=dict_row
        ) as connection:

            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT
                        blocked.pid AS blocked_pid,
                        blocked.usename AS blocked_user,
                        blocked.wait_event_type,
                        blocked.wait_event,
                        blocker.pid AS blocker_pid,
                        blocker.usename AS blocker_user,
                        blocker.state AS blocker_state,
                        blocker.query AS blocker_last_query,
                        now() - blocker.xact_start
                            AS blocker_transaction_duration
                    FROM pg_stat_activity AS blocked
                    CROSS JOIN LATERAL
                        unnest(pg_blocking_pids(blocked.pid))
                        AS blocker_pid(pid)
                    LEFT JOIN pg_stat_activity AS blocker
                        ON blocker.pid = blocker_pid.pid
                    WHERE blocked.datname = current_database();
                """)

                results = cursor.fetchall()

                return {
                    "database": "ai_dba_lab",
                    "blocking_session_count": len(results),
                    "blocking_sessions": [
                        {
                            **row,
                            "blocker_transaction_duration": (
                                str(row["blocker_transaction_duration"])
                                if row["blocker_transaction_duration"]
                                is not None else None
                            )
                        }
                        for row in results
                    ]
                }

    except (psycopg.Error, KeyError) as error:
        raise HTTPException(
            status_code=503,
            detail="Blocking-session monitoring unavailable"
        ) from error

@app.get("/analyze-blocking")
def analyze_blocking_endpoint():
    data = blocking_sessions()
    return analyze_blocking(data)


class DBAQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.post("/ask-dba")
def ask_dba(request: DBAQuestion):
    # Reuse our existing monitoring and rule-based analysis.
    incident_data = analyze_blocking(blocking_sessions())

    # Let the LLM explain verified monitoring findings.
    answer = explain_incident(
        question=request.question,
        incident_data=incident_data,
    )

    return {
        "question": request.question,
        "database_status": incident_data["status"],
        "incident_count": incident_data["incident_count"],
        "ai_explanation": answer,
        "requires_human_approval": True,
    }



@app.get("/long-running-queries")
def long_running_queries():
    query = """
        SELECT
            pid,
            usename AS username,
            clock_timestamp() - query_start AS query_duration,
            state,
            wait_event_type,
            wait_event
        FROM pg_stat_activity
        WHERE datname = current_database()
          AND state = 'active'
          AND pid <> pg_backend_pid()
          AND query_start <
              clock_timestamp() - INTERVAL '60 seconds'
    """

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            results = cur.fetchall()

    return {
        "database": "ai_dba_lab",
        "long_running_query_count": len(results),
        "long_running_queries": [
            {
                **row,
                "query_duration": str(row["query_duration"])
            }
            for row in results
        ]
    }

    @app.get("/analyze-long-queries")
    def analyze_long_queries():

    monitoring_data = long_running_queries()

    findings = []

    for query in monitoring_data["long_running_queries"]:

        analysis = classify_long_running_query(query)

        findings.append({
            "pid": query["pid"],
            "username": query["username"],
            "query_duration": query["query_duration"],
            "wait_event_type": query["wait_event_type"],
            "wait_event": query["wait_event"],
            "severity": analysis["severity"],
            "diagnosis": analysis["diagnosis"],
            "recommendation": analysis["recommendation"]
        })

    return {
        "database": monitoring_data["database"],
        "long_running_query_count": len(findings),
        "findings": findings,
        "requires_human_approval": True
    }


