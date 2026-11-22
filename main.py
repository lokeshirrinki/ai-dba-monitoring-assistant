import logging
import os

import psycopg
from fastapi import FastAPI, HTTPException
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from incident_analyzer import analyze_blocking
from llm_analyzer import explain_incident
from long_query_analyzer import classify_long_running_query

logger = logging.getLogger(__name__)
app = FastAPI(title="AI DBA Monitoring API", version="0.1.0")


class DBAQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=500)


def get_db_connection():
    return psycopg.connect(
        host="localhost",
        port=5432,
        dbname="ai_dba_lab",
        user="ai_monitor",
        password=os.environ["DB_PASSWORD"],
        connect_timeout=5,
        options="-c default_transaction_read_only=on",
        row_factory=dict_row,
    )


@app.get("/health")
def health():
    try:
        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT current_database() AS database,
                           current_user AS monitoring_user,
                           pg_size_pretty(pg_database_size(current_database()))
                               AS database_size,
                           clock_timestamp() - pg_postmaster_start_time()
                               AS server_uptime;
                """)
                database_info = cursor.fetchone()

                cursor.execute("""
                    SELECT COUNT(*) FILTER (WHERE state = 'active')
                               AS active_sessions,
                           COUNT(*) FILTER (WHERE state = 'idle')
                               AS idle_sessions,
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
                "server_uptime": str(database_info["server_uptime"]),
            },
            "session_statistics": session_info,
            "blocking_sessions": blocking_info,
            "blocked_session_count": len(blocking_info),
        }
    except (psycopg.Error, KeyError):
        logger.exception("Database health monitoring failed")
        raise HTTPException(
            status_code=503, detail="Database health monitoring unavailable"
        )


@app.get("/blocking-sessions")
def blocking_sessions():
    try:
        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT blocked.pid AS blocked_pid,
                           blocked.usename AS blocked_user,
                           blocked.wait_event_type,
                           blocked.wait_event,
                           blocker.pid AS blocker_pid,
                           blocker.usename AS blocker_user,
                           blocker.state AS blocker_state,
                           blocker.query AS blocker_last_query,
                           clock_timestamp() - blocker.xact_start
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
                        if row["blocker_transaction_duration"] is not None
                        else None
                    ),
                }
                for row in results
            ],
        }
    except (psycopg.Error, KeyError) as error:
        logger.exception("Blocking-session monitoring failed")
        raise HTTPException(
            status_code=503, detail="Blocking-session monitoring unavailable"
        ) from error


@app.get("/analyze-blocking")
def analyze_blocking_endpoint():
    return analyze_blocking(blocking_sessions())


@app.get("/long-running-queries")
def long_running_queries():
    try:
        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT pid,
                           usename AS username,
                           clock_timestamp() - query_start AS query_duration,
                           state,
                           wait_event_type,
                           wait_event
                    FROM pg_stat_activity
                    WHERE datname = current_database()
                      AND state = 'active'
                      AND query_start < clock_timestamp() - INTERVAL '60 seconds'
                      AND pid <> pg_backend_pid()
                    ORDER BY query_start ASC;
                """)
                results = cursor.fetchall()

        return {
            "database": "ai_dba_lab",
            "long_running_query_count": len(results),
            "long_running_queries": [
                {**row, "query_duration": str(row["query_duration"])}
                for row in results
            ],
        }
    except (psycopg.Error, KeyError) as error:
        logger.exception("Long-running query monitoring failed")
        raise HTTPException(
            status_code=503, detail="Long-running query monitoring unavailable"
        ) from error


@app.get("/analyze-long-queries")
def analyze_long_queries():
    data = long_running_queries()
    findings = []
    for query in data["long_running_queries"]:
        classification = classify_long_running_query(query)
        findings.append({
            "pid": query["pid"],
            "username": query["username"],
            "query_duration": query["query_duration"],
            "wait_event_type": query["wait_event_type"],
            "wait_event": query["wait_event"],
            **classification,
        })

    return {
        "database": data["database"],
        "long_running_query_count": len(findings),
        "findings": findings,
        "requires_human_approval": True,
    }


@app.post("/ask-dba")
def ask_dba(request: DBAQuestion):
    question = request.question.lower()
    long_query_keywords = (
        "long running", "long-running", "slow query", "slow queries",
        "running longer", "running for", "query duration",
    )
    blocking_keywords = (
        "blocking", "blocked", "blocker", "lock contention", "deadlock",
    )

    if any(keyword in question for keyword in long_query_keywords):
        analysis_type = "long_running"
        incident_data = analyze_long_queries()
        incident_count = incident_data["long_running_query_count"]
        database_status = (
            "long_running_queries_detected" if incident_count > 0
            else "no_long_running_queries_detected"
        )
    elif any(keyword in question for keyword in blocking_keywords):
        analysis_type = "blocking"
        incident_data = analyze_blocking(blocking_sessions())
        incident_count = incident_data["incident_count"]
        database_status = incident_data["status"]
    else:
        raise HTTPException(
            status_code=400,
            detail=("Unsupported question. Ask about blocking sessions "
                    "or long-running queries."),
        )

    try:
        answer = explain_incident(
            question=request.question,
            incident_data=incident_data,
            analysis_type=analysis_type,
        )
    except Exception as error:
        logger.exception("AI incident explanation failed")
        raise HTTPException(
            status_code=502, detail="AI incident explanation unavailable"
        ) from error

    return {
        "question": request.question,
        "analysis_type": analysis_type,
        "database_status": database_status,
        "incident_count": incident_count,
        "ai_explanation": answer,
        "requires_human_approval": True,
    }


