import json
import os
from urllib.parse import urlparse

from dotenv import load_dotenv
from azure.ai.contentunderstanding import ContentUnderstandingClient
from azure.ai.contentunderstanding.models import AnalysisInput, AnalysisResult
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import AzureError


load_dotenv()


def is_absolute_url(value: str) -> bool:
    parsed_url = urlparse(value)
    return bool(parsed_url.scheme and parsed_url.netloc)


def main() -> None:

    endpoint = "https://foundryegws.services.ai.azure.com/"
    key = os.getenv("API_KEY")

    file_url = (
        "https://raw.githubusercontent.com/Azure-Samples/"
        "azure-ai-content-understanding-assets/main/document/invoice.pdf"
    )

    analyzer_id = "prebuilt-read"
    api_version = "2026-06-01-preview"

    if not is_absolute_url(endpoint):
        print("[Error] Invalid Endpoint.")
        return

    if not is_absolute_url(file_url):
        print("[Error] Invalid File URL.")
        return

    if not key:
        print("[Error] API_KEY wurde nicht gefunden.")
        return

    credential = AzureKeyCredential(key)

    client = ContentUnderstandingClient(
        endpoint=endpoint,
        credential=credential,
        api_version=api_version
    )

    print(f"Analyzing with {analyzer_id} analyzer...")
    print(f"File URL: {file_url}\n")

    try:
        poller = client.begin_analyze(
            analyzer_id=analyzer_id,
            inputs=[AnalysisInput(url=file_url)],
        )

        result: AnalysisResult = poller.result()

    except AzureError as err:
        print(f"[Azure Error]: {err}")
        return

    except Exception as ex:
        print(f"[Unexpected Error]: {ex}")
        return

    print("=" * 50)
    print("Analysis result:")
    print("=" * 50)

    result_str = json.dumps(result.as_dict(), indent=2)

    print(result_str)


if __name__ == "__main__":
    main()