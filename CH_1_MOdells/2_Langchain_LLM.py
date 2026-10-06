from langchain.chat_models import init_chat_model
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("API_KEY")

llm_endpoint = "https://foundryegws.services.ai.azure.com/openai/v1"

llm = init_chat_model(
    model="azure_ai:gpt-5-mini",
    api_key=api_key,
    base_url=llm_endpoint,
)

response = llm.invoke("What is the capital of France?")

print(response.content)