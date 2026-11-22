
from google import genai

client = genai.Client()

response = client.models.generate_content(
    model="gemini-3.8-flash",
    contents=(
        "Explain PostgreSQL idle in transaction "
        "blocking in three simple sentences."
    )
)

print(response.text)
