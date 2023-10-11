"""
Functions, variables and classes for handling the transcription streams
"""
import asyncio
import logging
import subprocess
import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from collections import deque
import os
from functools import partial

from prometheus_client import Gauge
import websockets

from speechmatics.models import (
    ConnectionSettings,
    TranscriptionConfig,
    AudioSettings,
    ServerMessageType,
    RTTranslationConfig,
)
from speechmatics.client import WebsocketClient

streams_gauge = Gauge(
    "open_streams", "Amount of opened transcription/translation streams", ["language"]
)


LOGGER = logging.getLogger("server")
AUTH_TOKEN = os.environ["AUTH_TOKEN"]

CONNECTION_URL = os.getenv("SM_RT_RUNTIME_URL", "wss://neu.rt.speechmatics.com/v2")

ENABLE_TRANSCRIPTION_PARTIALS = os.getenv(
    "SM_ENABLE_TRANSCRIPTION_PARTIALS", "False"
).lower() in ("true", "1", "t")
ENABLE_TRANSLATION_PARTIALS = os.getenv(
    "SM_ENABLE_TRANSLATION_PARTIALS", "False"
).lower() in ("true", "1", "t")

MAX_DELAY = int(os.getenv("SM_MAX_DELAY", "3"))

FRAME_RATE = 16000
FFMPEG_OUTPUT_FORMAT = "f32le"
ENCODING = f"pcm_{FFMPEG_OUTPUT_FORMAT}"
settings = AudioSettings(encoding=ENCODING, sample_rate=FRAME_RATE)


@dataclass
class SupportedStream:
    """
    SupportedStream holds all the metadata about supported streams,
    including language, translations, and endpoint
    """

    url: str
    language: str
    translation_languages: list[str] = field(default_factory=list)


SUPPORTED_STREAMS: Dict[str, SupportedStream] = {
    "english": SupportedStream(
        url="https://stream.live.vc.bbcmedia.co.uk/bbc_world_service",
        # pylint: disable=locally-disabled, line-too-long
        # url="https://a.files.bbci.co.uk/media/live/manifesto/audio/simulcast/hls/uk/high/cfs/bbc_world_service.m3u8",
        language="en",
        translation_languages=["fr", "de", "ja", "ko", "es"],
    ),
    "german": SupportedStream(
        # pylint: disable=locally-disabled, line-too-long
        url="https://icecast.ndr.de/ndr/ndrinfo/niedersachsen/mp3/128/stream.mp3?1680704013057&aggregator=web",
        language="de",
        translation_languages=["en"],
    ),
    "french": SupportedStream(
        url="https://icecast.radiofrance.fr/franceinter-midfi.mp3",
        language="fr",
        translation_languages=["en"],
    ),
    "spanish": SupportedStream(
        url="https://22333.live.streamtheworld.com/CADENASERAAC_SC",
        language="es",
        translation_languages=["en"],
    ),
    "korean": SupportedStream(
        url="http://fmt01.egihosting.com:9468/",
        language="ko",
        translation_languages=["en"],
    ),
}


@dataclass
class StreamState:
    """
    StreamState is used to keep track of clients connected to the stream
    Also holds the current transcription process to allow process cancellation
    """

    internal_task: asyncio.Task
    connections: List = field(default_factory=list)
    previous_messages: deque = field(default_factory=partial(deque, maxlen=20))


# The Tuple key has a structure (name, language) e.g. (Radio 4, en)
STREAMS: Dict[Tuple[str, str], StreamState] = {}


# pylint: disable=locally-disabled, too-many-locals, too-many-statements
async def load_stream(stream_name: str):
    """
    Function used to initialise a supported stream

    Sets ffmpeg to read from the stream URL and opens a transcriber session to transcribe the stream
    """
    LOGGER.info("loading stream", extra={"stream": stream_name})
    stream_meta = SUPPORTED_STREAMS[stream_name]
    stream_url = stream_meta.url
    language = stream_meta.language

    conf = TranscriptionConfig(
        language=language,
        operating_point="enhanced",
        max_delay=MAX_DELAY,
        enable_partials=True,
        translation_config=RTTranslationConfig(
            target_languages=stream_meta.translation_languages, enable_partials=True
        ),
    )

    stream_with_arg = (
        f"{stream_url}?rcvbuf=15000000"
        if stream_url.startswith("srt://")
        else stream_url
    )
    ffmpegs_args = [
        *("-re",),
        # *("-v", "48"),
        *("-i", stream_with_arg),
        *("-f", FFMPEG_OUTPUT_FORMAT),
        *("-ar", FRAME_RATE),
        *("-ac", 1),
        *("-acodec", ENCODING),
        "-",
    ]
    LOGGER.info(
        "Running ffmpeg with args: %s", ffmpegs_args, extra={"stream": stream_name}
    )

    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        *map(str, ffmpegs_args),
        limit=1024 * 1024,  # 1 MiB reduces errors with long outputs (default is 64 KiB)
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    LOGGER.info("ffmpeg started", extra={"stream": stream_name})

    url = f"{CONNECTION_URL}/{language}?sm-app=radio-stream-translation-demo"

    LOGGER.info("Starting SM websocket client", extra={"url": url})

    start_time = time.time()
    sm_client = WebsocketClient(
        ConnectionSettings(
            url=url,
            auth_token=AUTH_TOKEN,
            generate_temp_token=True,
        )
    )
    sm_client.add_event_handler(
        event_name=ServerMessageType.AddTranscript,
        event_handler=partial(
            send_transcript,
            stream_name=stream_name,
            start_time=start_time,
        ),
    )
    sm_client.add_event_handler(
        event_name=ServerMessageType.AddPartialTranscript,
        event_handler=partial(
            send_transcript,
            stream_name=stream_name,
            start_time=start_time,
        ),
    )
    sm_client.add_event_handler(
        event_name=ServerMessageType.AddTranslation,
        event_handler=partial(
            send_translation,
            stream_name=stream_name,
            start_time=start_time,
        ),
    )
    sm_client.add_event_handler(
        event_name=ServerMessageType.AddPartialTranslation,
        event_handler=partial(
            send_translation,
            stream_name=stream_name,
            start_time=start_time,
        ),
    )
    sm_client.add_event_handler(
        event_name=ServerMessageType.EndOfTranscript,
        event_handler=partial(finish_session, stream_name=stream_name),
    )
    sm_client.add_event_handler(
        event_name=ServerMessageType.RecognitionStarted,
        event_handler=partial(receive_message, stream_name=stream_name),
    )
    sm_client.add_event_handler(
        event_name=ServerMessageType.Error,
        event_handler=partial(receive_message, stream_name=stream_name, level="error"),
    )
    sm_client.add_event_handler(
        event_name=ServerMessageType.Warning,
        event_handler=partial(
            receive_message, stream_name=stream_name, level="warning"
        ),
    )
    sm_client.add_event_handler(
        event_name=ServerMessageType.Info,
        event_handler=partial(receive_message, stream_name=stream_name),
    )

    try:
        runtime_stream = asyncio.StreamReader()
        broadcast_stream = asyncio.StreamReader()

        stream_clone_task = asyncio.create_task(
            stream_tee(
                process.stdout, runtime_stream, broadcast_stream, settings.chunk_size
            )
        )

        LOGGER.info(
            "Starting transcription",
            extra={"stream": stream_name},
        )
        asr_task = asyncio.create_task(sm_client.run(runtime_stream, conf, settings))
        send_audio_task = asyncio.create_task(send_audio(broadcast_stream, stream_name))
        log_task = asyncio.create_task(log_ffmpeg(process))

        done, pending = await asyncio.wait(
            [log_task, send_audio_task, asr_task, stream_clone_task],
            return_when=asyncio.FIRST_EXCEPTION,
        )
        async for done_routine in done:
            if done_routine.exception() is not None:
                LOGGER.error(
                    "Exception in return %s",
                    done_routine.exception(),
                    extra={"stream": stream_name},
                )
        async for pending_routine in pending:
            pending_routine.cancel()
            if pending_routine.exception() is not None:
                LOGGER.error(
                    "Exception in return %s",
                    pending_routine.exception(),
                    extra={"stream": stream_name},
                )

    except asyncio.CancelledError:
        LOGGER.warning("Task Cancelled", extra={"stream": stream_name})
    finally:
        LOGGER.warning("Stream %s exited, cleaning up tasks", stream_name)
        if stream_name in STREAMS:
            stream = STREAMS.pop(stream_name)
            streams_gauge.labels(stream_name).dec()
            LOGGER.info(
                "Popped closed transcription stream, closing all connections",
                extra={"stream": stream_name},
            )
            await force_close_connections(stream)
        sm_client.stop()
        await process.kill()
        await asr_task.cancel()
        await stream_clone_task.cancel()
        await send_audio_task.cancel()

    LOGGER.info("Finished transcription", extra={"stream": stream_name})


async def stream_tee(source, target, target_two, chunk_size):
    """
    This function splits stream data from a source stream into two target streams.
    """
    while True:
        data = await source.read(chunk_size)
        if not data:  # EOF
            break
        target.feed_data(data)
        target_two.feed_data(data)


async def send_audio(stream, stream_name):
    """
    broadcast audio to connected clients
    """
    while True:
        data = await stream.read(settings.chunk_size)
        if not data:
            break
        stream_state = STREAMS[stream_name]
        # pylint: disable=locally-disabled, no-member
        websockets.broadcast(stream_state.connections, data)


def send_transcript(message, stream_name, start_time):
    """
    Event handler function to send transcript data to the client
    """
    LOGGER.debug(
        "Received message from transcriber",
        extra={"stream": stream_name},
    )
    if stream_name not in STREAMS:
        # no clients to serve
        LOGGER.warning(
            "Tried to send transcript message to closed stream",
            extra={"stream": stream_name},
        )
        return

    LOGGER.debug("Received message from transcriber", extra={"stream": stream_name})

    message["current_timestamp"] = time.time()
    message["metadata"]["session_start_time"] = start_time
    stream_state = STREAMS[stream_name]
    LOGGER.debug("Received %s", message, extra={"stream": stream_name})
    LOGGER.debug(
        "Broadcasting message for %s clients",
        len(stream_state.connections),
        extra={"stream": stream_name},
    )
    # pylint: disable=locally-disabled, no-member
    websockets.broadcast(stream_state.connections, json.dumps(message))


def send_translation(message, stream_name, start_time):
    """
    Event handler function to send translation data to the client
    """
    if stream_name not in STREAMS:
        # no clients to serve
        LOGGER.warning(
            "Tried to send translation message to closed stream",
            extra={"stream": stream_name},
        )
        return

    message["current_timestamp"] = time.time()

    message["metadata"] = {"session_start_time": start_time}

    stream_state = STREAMS[stream_name]

    LOGGER.debug("Received %s", message, extra={"stream": stream_name})

    LOGGER.debug(
        "Broadcasting message to %s clients",
        len(stream_state.connections),
        extra={"stream": stream_name},
    )
    # pylint: disable=locally-disabled, no-member
    websockets.broadcast(stream_state.connections, json.dumps(message))


def finish_session(message, stream_name):
    """
    Handles finishing the session when end of transcript is reached
    """
    LOGGER.info(
        "Received end of transcript: %s", message, extra={"stream": stream_name}
    )
    if stream_name not in STREAMS:
        # no clients to serve
        return
    stream_state = STREAMS[stream_name]
    loop = asyncio.get_event_loop()
    for connection in stream_state.connections:
        loop.create_task(connection.close())


async def log_ffmpeg(process):
    """
    Log stderr from ffmpeg - ffmpeg writes all logs to stderr as
    """
    while True:
        line = (await process.stderr.readline()).decode("utf-8").strip()
        if len(line) == 0:
            break
        LOGGER.info(line, extra={"source": "ffmpeg"})


def receive_message(message, stream_name, level="debug"):
    """
    Receive messages
    """
    if stream_name not in STREAMS:
        # no clients to serve
        return

    stream_state = STREAMS[stream_name]

    if level == "info":
        LOGGER.info("Received %s", message, extra={"stream": stream_name})
    elif level == "warning":
        LOGGER.warning("Received %s", message, extra={"stream": stream_name})
        stream_state.previous_messages.append(message)
    elif level == "error":
        LOGGER.error("Received %s", message, extra={"stream": stream_name})
        stream_state.previous_messages.append(message)
    elif level == "debug":
        LOGGER.debug("Received %s", message, extra={"stream": stream_name})

    # pylint: disable=locally-disabled, no-member
    websockets.broadcast(stream_state.connections, json.dumps(message))


async def force_close_connections(stream):
    """
    Force closes all websocket connections for a particular stream.
    Used when the stream dies unexpectedly.
    """
    LOGGER.warning("Force closing all connections")
    for conn in stream.connections:
        await conn.close(1011, "An unexpected error occurred on the server")
