from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()

llm_endpoint = "https://foundryegws.services.ai.azure.com/openai/v1"
deployment_name = "gpt-5-mini"

api_key = os.getenv("API_KEY")

client = OpenAI(
    base_url=llm_endpoint,
    api_key=api_key
)

response = client.responses.create(
    model=deployment_name,
    input="What is the capital of France?",
)

print(response.output_text)