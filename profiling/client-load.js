import ws from 'k6/ws';
import { check } from 'k6';

export const options = {
  discardresponsebodies: true,
  scenarios: {
    users: {
      executor: "ramping-vus",
      startvus: 1,
      stages: [
        { duration: '1m', target: 1 },
        { duration: '2m', target: 200 },
        { duration: '5m', target: 200 },
        { duration: '2m', target: 1 },
        { duration: '1m', target: 1 },
      ],
    },
  },
};

export default function () {
  const url = 'ws://127.0.0.1:8765';
  const res = ws.connect(url, function (socket) {
    socket.on('open', function open() {
      console.log('connected')
      const streams = ["english", "german", "french", "spanish"];
      const random = Math.floor(Math.random() * streams.length);
      socket.send(`{"name": "${streams[random]}"}`)
    });
    // socket.on('message', (data) => console.log('Message received: ', data));
    socket.on('close', () => console.log('disconnected'));
  });
  check(res, { 'status is 101': (r) => r && r.status === 101 });
}
