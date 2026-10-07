# coding=utf-8
"""
Hold a hands-free, bidirectional audio conversation with an existing Microsoft
Foundry voice agent, then read the persisted conversation back.

The agent, model, instructions, voice, and tools are already configured in
Foundry and are applied automatically when the session connects. Microphone
audio is streamed as PCM16; reply audio is played through the speakers. The
agent owns turn detection and noise suppression server-side, so this sample
sends no session configuration.

Requires:
  pip install azure-ai-voiceagents azure-ai-voicelive[aiohttp] azure-identity pyaudio
  az login

Use a headset to avoid echo. Press Ctrl-C to stop. The existing agent must have
conversation storage enabled for readback.
"""

import asyncio
import base64
import queue
from typing import Any, Final, Optional
from urllib.parse import quote, urlparse, urlunparse

import aiohttp
from azure.core.exceptions import HttpResponseError
from azure.core.pipeline.transport import AioHttpTransport
from azure.identity.aio import DefaultAzureCredential
from azure.ai.voiceagents.aio import VoiceAgentsClient
from azure.ai.voiceagents.models import AgentDefinitionOptInKeys
from azure.ai.voicelive.aio import connect
from azure.ai.voicelive.models import (
    ServerEventConversationItemInputAudioTranscriptionCompleted,
    ServerEventError,
    ServerEventInputAudioBufferSpeechStarted,
    ServerEventResponseAudioDelta,
    ServerEventResponseAudioTranscriptDone,
)

PREVIEW: Final = AgentDefinitionOptInKeys.VOICE_AGENTS_V1_PREVIEW
FOUNDRY_FEATURES: Final = {"Foundry-Features": "VoiceAgents=V1Preview"}
REALTIME_API_VERSION: Final = "2025-11-15-preview"
SAMPLE_RATE: Final = 24000
CHUNK_SAMPLES: Final = 1200
PROJECT_ENDPOINT = "https://foundryprojekt.services.ai.azure.com/api/projects/proj-default"
AGENT_NAME = "eager-agent-bdfxcyzlw9"


def voice_agent_realtime_url(project_endpoint: str, agent_name: str) -> str:
    """Build the WebSocket URL for the existing agent's realtime route."""
    parsed = urlparse(project_endpoint)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    encoded_name = quote(agent_name, safe="")
    path = parsed.path.rstrip("/") + f"/agents/{encoded_name}/endpoint/protocols/voice"
    return urlunparse(
        (scheme, parsed.netloc, path, "", f"api-version={REALTIME_API_VERSION}", "")
    )


try:
    import pyaudio
except ImportError:
    pyaudio = None  # type: ignore[assignment]


class AudioProcessor:
    """Capture microphone audio and play replies with barge-in support."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._audio = pyaudio.PyAudio()
        self._playback_queue: "queue.Queue[tuple[int, Optional[bytes]]]" = queue.Queue()
        self._playback_base = 0
        self._next_sequence = 0
        self._received_bytes = 0
        self._input_stream = None
        self._output_stream = None

    def start_capture(self) -> None:
        """Start streaming microphone audio to the service."""
        if self._input_stream is not None:
            return
        self._loop = asyncio.get_running_loop()

        def capture_callback(in_data, _frame_count, _time_info, _status):
            audio = base64.b64encode(in_data).decode("utf-8")
            assert self._loop is not None
            asyncio.run_coroutine_threadsafe(
                self._connection.input_audio_buffer.append(audio=audio),
                self._loop,
            )
            return (None, pyaudio.paContinue)

        self._input_stream = self._audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SAMPLES,
            stream_callback=capture_callback,
        )

    def start_playback(self) -> None:
        """Start playing response audio through the speakers."""
        if self._output_stream is not None:
            return
        remaining = b""

        def playback_callback(_in_data, frame_count, _time_info, _status):
            nonlocal remaining
            wanted = frame_count * pyaudio.get_sample_size(pyaudio.paInt16)
            output = remaining[:wanted]
            remaining = remaining[wanted:]

            while len(output) < wanted:
                try:
                    sequence, data = self._playback_queue.get_nowait()
                except queue.Empty:
                    output += bytes(wanted - len(output))
                    continue
                if not data:
                    break
                if sequence < self._playback_base:
                    remaining = b""
                    continue
                take = wanted - len(output)
                output += data[:take]
                remaining = data[take:]

            return (output, pyaudio.paContinue)

        self._output_stream = self._audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            output=True,
            frames_per_buffer=CHUNK_SAMPLES,
            stream_callback=playback_callback,
        )

    def next_sequence(self) -> int:
        sequence = self._next_sequence
        self._next_sequence += 1
        return sequence

    def queue_audio(self, pcm: bytes) -> None:
        self._received_bytes += len(pcm)
        self._playback_queue.put((self.next_sequence(), pcm))

    def skip_pending_audio(self) -> None:
        self._playback_base = self.next_sequence()

    def shutdown(self) -> None:
        if self._input_stream is not None:
            self._input_stream.stop_stream()
            self._input_stream.close()
            self._input_stream = None
        if self._output_stream is not None:
            self.skip_pending_audio()
            self._playback_queue.put((self.next_sequence(), None))
            self._output_stream.stop_stream()
            self._output_stream.close()
            self._output_stream = None
        self._audio.terminate()

    @property
    def seconds(self) -> float:
        return self._received_bytes / 2 / SAMPLE_RATE


async def run_audio_conversation(
    credential: DefaultAzureCredential,
) -> Optional[str]:
    """Hold a live audio conversation and return its persisted id."""
    if pyaudio is None:
        print("This sample needs pyaudio: pip install pyaudio")
        return None

    session = connect(
        credential=credential,
        endpoint=PROJECT_ENDPOINT,
        api_version=REALTIME_API_VERSION,
        headers=FOUNDRY_FEATURES,
    )
    session._prepare_url = lambda: voice_agent_realtime_url(  # type: ignore[attr-defined]
        PROJECT_ENDPOINT, AGENT_NAME
    )

    conversation_id: Optional[str] = None
    async with session as connection:
        audio = AudioProcessor(connection)
        audio.start_playback()
        audio.start_capture()

        print(f"Connected to existing voice agent: {AGENT_NAME}")
        print("Speak now -- talk over the agent to interrupt it; press Ctrl-C to stop.")

        try:
            async for event in connection:
                if isinstance(event, ServerEventInputAudioBufferSpeechStarted):
                    audio.skip_pending_audio()
                    print("(listening...)")
                elif isinstance(
                    event,
                    ServerEventConversationItemInputAudioTranscriptionCompleted,
                ):
                    print(f"You:   {event.transcript.strip()}")
                elif isinstance(event, ServerEventError):
                    print(f"Session error: {event.error.message}")
                elif isinstance(event, ServerEventResponseAudioDelta):
                    audio.queue_audio(event.delta)
                elif isinstance(event, ServerEventResponseAudioTranscriptDone):
                    print(f"Agent: {event.transcript}")
                elif event.type == "conversation.created":
                    conversation_id = event.get("conversation_id") or conversation_id
                    print(f"(persisted conversation: {conversation_id})")
        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\n(ending session...)")
        finally:
            print(f"(received {audio.seconds:.2f}s of reply audio)")
            audio.shutdown()

    return conversation_id


async def read_conversation(
    client: VoiceAgentsClient, conversation_id: str
) -> None:
    """Read the stored conversation created by the live session."""
    conversations = client.agent_endpoint_conversations
    conversation = await conversations.get_agent_conversation(
        AGENT_NAME,
        conversation_id,
        foundry_features=PREVIEW,
    )
    print(
        f"Conversation {conversation.id}: "
        f"status={conversation.status}, created_at={conversation.created_at}"
    )

    print("Items (transcript):")
    async for item in conversations.list_agent_conversation_items(
        AGENT_NAME,
        conversation_id,
        foundry_features=PREVIEW,
    ):
        role = item.get("role") or item.get("type")
        parts = [
            (part.get("transcript") or part.get("text") or "").strip()
            for part in (item.get("content") or [])
        ]
        transcript = " ".join(part for part in parts if part)
        print(f"  - {role} id={item.get('id')}")
        if transcript:
            print(f"      {transcript}")


async def conversation_with_existing_agent() -> None:
    credential = DefaultAzureCredential()
    transport = AioHttpTransport(
        session=aiohttp.ClientSession(
            auto_decompress=False,
            headers={"Accept-Encoding": "gzip, deflate"},
        )
    )

    async with credential, VoiceAgentsClient(
        endpoint=PROJECT_ENDPOINT,
        credential=credential,
        transport=transport,
    ) as client:
        conversation_id = await run_audio_conversation(credential)
        if conversation_id:
            print(f"Reading persisted conversation {conversation_id}...")
            try:
                await read_conversation(client, conversation_id)
            except HttpResponseError as error:
                response = getattr(error, "response", None)
                text = response.text() if response is not None else ""
                print(
                    f"Could not read conversation: "
                    f"{error.status_code} {error.reason}\n{text}"
                )
        else:
            print("No conversation id was returned; nothing to read.")


if __name__ == "__main__":
    try:
        asyncio.run(conversation_with_existing_agent())
    except KeyboardInterrupt:
        print("\nInterrupted.")
