import asyncio
import json
import logging

import pytest
import pytest_asyncio
from websockets.asyncio.client import connect

from stream_transcriber.server import create_server


@pytest_asyncio.fixture
async def server_port():
    async with create_server("127.0.0.1", 0) as server:
        yield server.sockets[0].getsockname()[1]


async def plain_http_get(port, path="/demo"):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(
        f"GET {path} HTTP/1.1\r\n"
        "Host: stream-demo-production-weu.speechmatics.com\r\n"
        "User-Agent: Azure Traffic Manager Endpoint Monitor\r\n"
        "Connection: close\r\n\r\n".encode()
    )
    await writer.drain()
    response = await asyncio.wait_for(reader.read(), timeout=5)
    writer.close()
    return response.decode()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/", "/demo"])
async def test_plain_http_request_gets_ok_without_logging_errors(
    server_port, path, caplog
):
    # Health probes (e.g. Azure Traffic Manager) send plain HTTP requests without
    # a websocket upgrade. They must get a 200 and must not be logged as errors.
    with caplog.at_level(logging.INFO, logger="websockets"):
        response = await plain_http_get(server_port, path)

    assert response.startswith("HTTP/1.1 200 OK"), response
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors == [], [r.getMessage() for r in errors]


@pytest.mark.asyncio
async def test_websocket_connection_still_accepted(server_port):
    async with connect(f"ws://127.0.0.1:{server_port}/demo") as websocket:
        message = json.loads(await asyncio.wait_for(websocket.recv(), timeout=5))
    assert message["message"] == "Initialised"
