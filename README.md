# Stream Radio Server

A Python Websocket Server for transcribing/translating multiple radio streams and allowing clients to subscribe to the results.

## Getting Started

Install all the required dependencies with:

```
brew install ffmpeg
pip3 install -r requirements.txt
```

## Running

Start the server with

```bash
python3 -m stream_transcriber.server --port 8765
```

Connect with your client to e.g. `ws://localhost:8765`, 
with https://github.com/vi/websocat this can be done with:
```bash
websocat ws://127.0.0.1:8765
```
> {"message": "Initialised", "info": "Waiting for message specyifing desired stream url"}

The server expects an initial JSON message with the desired language to start streaming:
```json
{"name": "english"}
```

Now the client will receive audio chunks and messages in JSON format until the stream ends or the client disconnects.

## Running tests

Run the following command

```bash
make unittest
```

The above command runs the tests in a docker container with the intended Python version and all dependencies installed. For running the tests directly on your computer run the following command

```bash
make unittest-local
```