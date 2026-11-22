
from groq import Groq

client = Groq(timeout=20.0, max_retries=0)

response = client.chat.completions.create(
    model="openai/gpt-oss-20b",
    messages=[
        {
            "role": "system",
            "content": (
                "You are a PostgreSQL DBA assistant. "
                "Explain incidents accurately and recommend "
                "safe troubleshooting steps."
            ),
        },
        {
            "role": "user",
            "content": (
                "Explain PostgreSQL idle in transaction "
                "blocking in three simple sentences."
            ),
        },
    ],
    max_completion_tokens=1000,
    reasoning_effort="low",
)

print(response.choices[0].message.content)
