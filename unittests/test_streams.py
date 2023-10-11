import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stream_transcriber.streams import (
    SUPPORTED_STREAMS,
    finish_session,
    force_close_connections,
    load_stream,
    receive_message,
    send_audio,
    send_transcript,
    send_translation,
    stream_tee,
)
from unittests.conftest import CustomAsyncMock


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source_content",
    [
        b"test",
        b"",
        b"hello world",
        b"12345",
    ],
)
async def test_stream_tee(source_content):
    source = asyncio.StreamReader()
    source.feed_data(source_content)
    source.feed_eof()

    target_one = asyncio.StreamReader()
    target_two = asyncio.StreamReader()

    await stream_tee(source, target_one, target_two, 4)

    assert await target_one.read(len(source_content)) == source_content
    assert await target_two.read(len(source_content)) == source_content


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"audio-content", b""])
async def test_send_audio(stream, content):
    stream_key, stream_state = stream
    audio_stream = asyncio.StreamReader()
    audio_stream.feed_data(content)
    audio_stream.feed_eof()

    stream_state.connections = [MagicMock()]

    with patch("websockets.broadcast") as mock_broadcast:
        await send_audio(audio_stream, stream_key)
        if content:
            mock_broadcast.assert_called_with(stream_state.connections, content)
        else:
            mock_broadcast.assert_not_called()


def test_send_transcript_for_closed_stream():
    with patch("stream_transcriber.streams.LOGGER") as mock_logger:
        with patch("websockets.broadcast") as mock_broadcast:
            send_transcript({}, "not-opened", "2023-01-01T00:00:00.000Z")
            mock_broadcast.assert_not_called()
            assert "Tried to send transcript message to closed stream" in str(
                mock_logger.warning.call_args_list[0]
            )


def test_send_transcript(stream):
    stream_key, stream_state = stream
    stream_state.connections = [MagicMock()]

    session_start_time = "2023-01-01T00:00:00.000Z"
    transcript = {"metadata": {}}

    expected_sent_transcript = transcript.copy()
    mocked_time = 1696780852
    with patch("time.time", return_value=mocked_time):
        expected_sent_transcript["current_timestamp"] = mocked_time
        expected_sent_transcript["metadata"]["session_start_time"] = session_start_time
        with patch("websockets.broadcast") as mock_broadcast:
            send_transcript(transcript, stream_key, session_start_time)
            mock_broadcast.assert_called_with(
                stream_state.connections, json.dumps(expected_sent_transcript)
            )


def test_send_translation_for_closed_stream():
    with patch("stream_transcriber.streams.LOGGER") as mock_logger:
        with patch("websockets.broadcast") as mock_broadcast:
            send_translation({}, "not-opened", "2023-01-01T00:00:00.000Z")
            mock_broadcast.assert_not_called()
            assert "Tried to send translation message to closed stream" in str(
                mock_logger.warning.call_args_list[0]
            )


def test_send_translation(stream):
    stream_key, stream_state = stream
    stream_state.connections = [MagicMock()]

    session_start_time = "2023-01-01T00:00:00.000Z"
    translation = {"metadata": {}}

    expected_sent_translation = translation.copy()
    mocked_time = 1696780852
    with patch("time.time", return_value=mocked_time):
        expected_sent_translation["current_timestamp"] = mocked_time
        expected_sent_translation["metadata"]["session_start_time"] = session_start_time
        with patch("websockets.broadcast") as mock_broadcast:
            send_translation(translation, stream_key, session_start_time)
            mock_broadcast.assert_called_with(
                stream_state.connections, json.dumps(expected_sent_translation)
            )


def test_finish_session_with_closed_stream():
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value = MagicMock()
        finish_session({}, "not-opened")
        mock_loop.return_value.create_task.assert_not_called()


@pytest.mark.parametrize("amount_connections", [0, 1, 2])
def test_finish_session(stream, amount_connections):
    stream_key, stream_state = stream
    stream_state.connections = []
    for _ in range(amount_connections):
        stream_state.connections.append(MagicMock())

    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value = MagicMock()
        finish_session({}, stream_key)
        assert mock_loop.return_value.create_task.call_count == amount_connections


def test_receive_message_for_closed_stream():
    with patch("websockets.broadcast") as mock_broadcast:
        receive_message({}, "not-opened")
        mock_broadcast.assert_not_called()


@pytest.mark.parametrize("level", ["info", "warning", "error", "debug"])
def test_receive_message(stream, level):
    stream_key, stream_state = stream
    stream_state.previous_messages = []
    message = {"metadata": {}}
    with patch("websockets.broadcast") as mock_broadcast:
        receive_message(message, stream_key, level)
        mock_broadcast.assert_called_with(stream_state.connections, json.dumps(message))
        # messages received with level warning or error are also appended to the stream previous_messages
        if level in ("warning", "error"):
            assert len(stream_state.previous_messages) == 1
            assert stream_state.previous_messages[0] == message


@pytest.mark.asyncio
@pytest.mark.parametrize("amount_connections", [0, 1, 2])
async def test_force_close_connections(stream, amount_connections):
    _, stream_state = stream
    stream_state.connections = []
    for _ in range(amount_connections):
        stream_state.connections.append(AsyncMock())

    await force_close_connections(stream_state)

    for connection in stream_state.connections:
        connection.close.assert_called_once()


@pytest.mark.asyncio
@patch("asyncio.create_subprocess_exec")
@patch("asyncio.wait", new=AsyncMock(return_value=(AsyncMock(), AsyncMock())))
async def test_load_stream(mock_wait, stream):
    stream_key, stream_state = stream
    with patch("asyncio.create_task") as mock_create_task:
        mock_create_task.return_value = CustomAsyncMock()
        with patch(
            "stream_transcriber.streams.force_close_connections"
        ) as mock_force_close:
            await load_stream(stream_key)
            # Active stream should call force_close_connections
            mock_force_close.assert_called_once_with(stream_state)

            # Inactive stream should not call force_close_connections
            mock_force_close.reset_mock()
            closed_stream = next(
                key for key in SUPPORTED_STREAMS.keys() if key != stream_key
            )
            await load_stream(closed_stream)
            mock_force_close.assert_not_called()
