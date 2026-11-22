
import getpass
import json
from datetime import datetime
import psycopg
from psycopg.rows import dict_row

password = getpass.getpass("Enter ai_monitor password: ")

try:
    with psycopg.connect(
        host="localhost",
        port=5432,
        dbname="ai_dba_lab",
        user="ai_monitor",
        password=password,
        connect_timeout=5,
        options="-c default_transaction_read_only=on",
        row_factory=dict_row
    ) as connection:

        with connection.cursor() as cursor:

            # 1. Database information
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

            # 2. Session statistics
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

            # 3. Blocking-session information
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

            # 4. Build the health report
            report = {
                "database_info": database_info,
                "session_statistics": session_info,
                "blocking_sessions": blocking_info,
                "blocked_session_count": len(blocking_info),
                "report_generated_at": datetime.now().isoformat()
            }

            print(json.dumps(report, indent=4, default=str))

except psycopg.Error as error:
    print("Database monitoring failed:", error)
