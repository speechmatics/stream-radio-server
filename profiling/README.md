# Profiling the server under load

## Dependencies

In addition to the dependencies needed to run the server, you'll need the following:


- cli tools:
    - k6
    - ffmpeg
- Python packages:
    - memory_profiler
    - matplotlib

## Run profiling

We can collect some statistics while the server is under load:

1. Start the server with mprofile to get an evolution of memory consumption over time. It'll track also memory of child processes (ffmpeg)

```bash
SM_MANAGEMENT_PLATFORM_URL='<URL_TO_MGMT_PLATFORM>' AUTH_TOKEN='<API_KEY_HERE>' mprof run --multiprocess python3 -m stream_transcriber.server --port 8765
```

2. A simple way to keep an eye of cpu usage while the server is running. In another terminal:

```bash
# 1. Find the pid of the server
ps | grep server.py

# 2. Watch snapshots every 1s
watch -n 1 'ps -p <pid> -o %cpu,%mem,cmd'
```

1. Generate some load using [k6](https://k6.io)

```bash
k6 run profiling/client-load.js
```
NOTE: for really high numbers of clients you might hit the max number of file descriptors allowed to be open. Find how to change it for your OS. In MacOS the number can be retrieved with `ulimit -n`. It can be changed with `ulimit -n <amount>`

4. The snapshots every 1 second of cpu and mem will be showing in the separate terminal.

5. To visualize the graph of memory consumption over time, Ctrl + C in the terminal in which the server is running to stop it from running. Now use:

```bash
mprof plot
```
