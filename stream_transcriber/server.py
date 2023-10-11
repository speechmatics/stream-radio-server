"""
Main server entry point
"""

import asyncio
import datetime
import logging
import json
import os
import signal
from argparse import ArgumentParser
import traceback
from prometheus_client import start_http_server, Gauge

import websockets
from websockets.exceptions import ConnectionClosed

from stream_transcriber.streams import (
    SUPPORTED_STREAMS,
    STREAMS,
    StreamState,
    load_stream,
    streams_gauge,
)

LOGGER = logging.getLogger("server")
SM_STREAM_TIMEOUT = os.getenv("SM_STREAM_TIMEOUT", "10")
clients_gauge = Gauge(
    "connected_clients", "Amount of clients connected to the ws server"
)


async def close_stream_with_delay(key):
    """
    Function to close the transcriber stream when the number of connections drops to 0
    """
    try:
        stream_state = STREAMS[key]
    except KeyError:
        LOGGER.warning("Stream %s not found in the streams dictionary", key)
        return

    if len(stream_state.connections) > 0:
        return

    await asyncio.sleep(int(SM_STREAM_TIMEOUT))
    if len(stream_state.connections) > 0:
        return

    try:
        LOGGER.info("No connections left. Closing transcription", extra={"stream": key})
        stream_state.internal_task.cancel()
        await stream_state.internal_task
    finally:
        LOGGER.info("Closed stream %s as no more clients are connected", key)


async def ws_handler(websocket):
    """
    Websocket handler - receives client connections and attaches them to the correct audio stream
    """
    try:
        stream_name = None
        LOGGER.info("Client connected")
        await websocket.send(
            json.dumps(
                {
                    "message": "Initialised",
                    "info": "Waiting for message specifing desired stream url",
                }
            )
        )
        stream_data = json.loads(await websocket.recv())
        LOGGER.info("Received stream connection data %s", stream_data)
        if "name" not in stream_data:
            raise ValueError("Stream name not specified")

        stream_name = stream_data["name"]
        if stream_name not in SUPPORTED_STREAMS:
            raise ValueError(f"stream {stream_name} is not supported")

        if stream_name in STREAMS:
            LOGGER.info("already started", extra={"stream": stream_name})
            STREAMS[stream_name].connections.append(websocket)
            for old_message in STREAMS[stream_name].previous_messages:
                await websocket.send(json.dumps(old_message))
        else:
            LOGGER.info(
                "Creating a new Transcription session", extra={"stream": stream_name}
            )
            STREAMS[stream_name] = StreamState(
                internal_task=asyncio.create_task(load_stream(stream_name)),
                connections=[websocket],
            )
            streams_gauge.labels(stream_name).inc()

        with clients_gauge.track_inprogress():
            await websocket.wait_closed()
    except json.JSONDecodeError as error:
        LOGGER.warning(
            "Error decoding incoming JSON message with stream name: %s", error
        )
    except ValueError as error:
        LOGGER.warning(
            "Non recognized stream in incoming select stream message: %s", error
        )
    except (
        asyncio.InvalidStateError,
        asyncio.CancelledError,
        asyncio.IncompleteReadError,
        ConnectionClosed,
    ) as error:
        LOGGER.error("Error in websocket connection handler: %s", error)
    except Exception:  # pylint: disable=broad-except
        LOGGER.error(
            "Unexpected exception in websocket connection handler:\n %s",
            traceback.format_exc(),
        )
    finally:
        LOGGER.info("Connection closed, cleaning up")
        if stream_name and stream_name in STREAMS:
            stream_state = STREAMS[stream_name]
            stream_state.connections.remove(websocket)
            await close_stream_with_delay(stream_name)


async def main(port):
    """
    Main entry point for the websocket server
    """
    LOGGER.info("Starting WebSocket Server")
    # Set the stop condition when receiving SIGTERM.
    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    loop.add_signal_handler(signal.SIGTERM, stop.set_result, None)
    # pylint: disable=locally-disabled, no-member
    async with websockets.serve(ws_handler, "0.0.0.0", port):
        await stop  # Wait for SIGTERM


class ExtraFormatter(logging.Formatter):
    """
    Extra formatter for logging more context like stream name
    """

    def format(self, record: logging.LogRecord) -> str:
        default_attrs = logging.LogRecord(
            None, None, None, None, None, None, None
        ).__dict__.keys()
        extras = set(record.__dict__.keys()) - default_attrs
        log_items = [
            (
                '"msg": "%(message)s", "time": "%(asctime)s",'
                '"level": "%(levelname)s", "source": "%(name)s"'
            )
        ]
        for attr in extras:
            log_items.append(f'"{attr}": "%({attr})s"')
        format_str = f'{{{", ".join(log_items)}}}'
        # pylint: disable=locally-disabled, protected-access
        self._style._fmt = format_str
        record.levelname = record.levelname.lower()
        record.msg = record.msg.replace('"', r"\"")
        return super().format(record)

    def formatTime(self, record, datefmt=None):
        return datetime.datetime.fromtimestamp(record.created).isoformat()


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "--port", default=8765, type=int, help="Port for the Websocket server"
    )
    args = parser.parse_args()
    FORMAT_STRING = (
        '{"msg": "%(message)s","time": "%(asctime)s", '
        '"source": "%(name)s", "level": "%(levelname)s"}'
    )
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "debug").upper(), format=FORMAT_STRING
    )
    logging.Formatter.formatTime = (
        lambda self, record, datefmt=None: datetime.datetime.fromtimestamp(
            record.created
        ).isoformat()
    )
    handler = logging.StreamHandler()
    formatter = ExtraFormatter()
    handler.setFormatter(formatter)
    LOGGER.setLevel(os.getenv("LOG_LEVEL", "debug").upper())

    # Start server for exposing metrics
    start_http_server(8000)

    asyncio.run(main(args.port))
