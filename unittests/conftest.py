from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture(scope="session", autouse=True)
def set_sm_stream_timeout():
    with patch("stream_transcriber.server.SM_STREAM_TIMEOUT", 1):
        yield


@pytest.fixture(scope="function")
def stream():
    stream_state = MagicMock()

    stream_state.internal_task = CustomAsyncMock()
    stream_state.internal_task.cancel = MagicMock()

    stream_key = "english"
    patcher = patch.dict(
        "stream_transcriber.server.STREAMS", {stream_key: stream_state}
    )
    patcher.start()

    yield stream_key, stream_state
    patcher.stop()


@pytest.fixture()
def ws_server_protocol(recv_content, send_content):
    mock_websocket = MagicMock()

    async def recv():
        return recv_content

    async def send(content):
        return send_content

    mock_websocket.recv = MagicMock(side_effect=recv)
    mock_websocket.send = MagicMock(side_effect=send)

    return mock_websocket


class CustomAsyncMock(MagicMock):
    def __call__(self, *args, **kwargs):
        sup = super(CustomAsyncMock, self)

        async def coro():
            return sup.__call__(*args, **kwargs)

        return coro()

    def __await__(self):
        return self().__await__()
