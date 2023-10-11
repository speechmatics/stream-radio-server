import asyncio
import pytest
from unittest.mock import MagicMock, patch

from stream_transcriber.server import close_stream_with_delay, ws_handler, STREAMS


@pytest.mark.asyncio
async def test_closes_stream_when_stream_does_not_exist():
    with patch("stream_transcriber.server.LOGGER") as mock_logger:
        key = "non_existing_stream_key"
        await close_stream_with_delay(key)
        mock_logger.warning.assert_called_with(
            "Stream %s not found in the streams dictionary", key
        )


@pytest.mark.asyncio
async def test_does_not_close_stream_when_connections_exist(stream):
    stream_key, stream_state = stream
    stream_state.connections = [MagicMock()]

    with patch("stream_transcriber.server.LOGGER") as mock_logger:
        await close_stream_with_delay(stream_key)
        stream_state.internal_task.cancel.assert_not_called()
        mock_logger.info.assert_not_called()


@pytest.mark.asyncio
async def test_does_not_close_stream_when_connections_reappear(stream):
    stream_key, stream_state = stream
    stream_state.connections = []

    async def add_connection():
        await asyncio.sleep(0.5)
        stream_state.connections.append(MagicMock())

    with patch("stream_transcriber.server.LOGGER") as mock_logger:
        await asyncio.gather(close_stream_with_delay(stream_key), add_connection())
        stream_state.internal_task.cancel.assert_not_called()
        mock_logger.info.assert_not_called()


@pytest.mark.asyncio
async def test_close_stream_when_no_connections_left(stream):
    stream_key, stream_state = stream
    stream_state.connections = []

    await close_stream_with_delay(stream_key)
    stream_state.internal_task.cancel.assert_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("recv_content,send_content", [("not-json", "")])
async def test_ws_handler_non_json_stream_select_message(ws_server_protocol):
    with patch("stream_transcriber.server.LOGGER") as mock_logger:
        await ws_handler(ws_server_protocol)
        assert "Error decoding incoming JSON message with stream name" in str(
            mock_logger.warning.call_args_list[0]
        )
        assert STREAMS == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("recv_content,send_content", [('{"foo":"bar"}', "")])
async def test_ws_handler_bad_format_in_stream_select_message(ws_server_protocol):
    with patch("stream_transcriber.server.LOGGER") as mock_logger:
        await ws_handler(ws_server_protocol)
        assert "Non recognized stream in incoming select stream message" in str(
            mock_logger.warning.call_args_list[0]
        )
        assert STREAMS == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("recv_content,send_content", [('{"name":"english"}', "")])
async def test_ws_handler_first_connection_for_stream(ws_server_protocol):
    with patch("stream_transcriber.server.load_stream") as mock_load_stream:
        with patch("stream_transcriber.server.LOGGER") as mock_logger:
            await ws_handler(ws_server_protocol)
            assert any(
                "Creating a new Transcription session" in str(args)
                for args, _ in mock_logger.info.call_args_list
            )
            assert "english" in STREAMS
            assert STREAMS["english"].connections is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("recv_content,send_content", [('{"name":"english"}', "")])
async def test_ws_handler_connection_for_existing_stream(ws_server_protocol, stream):
    with patch("stream_transcriber.server.LOGGER") as mock_logger:
        await ws_handler(ws_server_protocol)
        assert any(
            "already started" in str(args)
            for args, _ in mock_logger.info.call_args_list
        )
        assert "english" in STREAMS
        assert STREAMS["english"].connections.append.called
