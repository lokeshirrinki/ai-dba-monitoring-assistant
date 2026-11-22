
import getpass
import psycopg

# Ask for the monitoring account password
password = getpass.getpass("Enter ai_monitor password: ")

try:
    # Establish a read-only database connection
    with psycopg.connect(
        host="localhost",
        port=5432,
        dbname="ai_dba_lab",
        user="ai_monitor",
        password=password,
        connect_timeout=5,
        options="-c default_transaction_read_only=on"
    ) as connection:

        # Execute our first monitoring query
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT current_database(),
                       current_user,
                       pg_postmaster_start_time();
            """)

            result = cursor.fetchone()

            print("\nDatabase connection successful!")
            print("Database:", result[0])
            print("Connected user:", result[1])
            print("Server started at:", result[2])

except psycopg.Error as error:
    print("Database connection or query failed!")
    print("Error:", error)
