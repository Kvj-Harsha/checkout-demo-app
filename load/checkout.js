import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  thresholds: {
    'http_req_duration': ['p(95)<1000'],
  },
};

export default function () {
  const response = http.post(
    'http://host.docker.internal:8000/checkout',
    JSON.stringify({ order_id: `demo-${__VU}-${__ITER}` }),
    { headers: { 'Content-Type': 'application/json' } },
  );
  check(response, { 'checkout responded': (res) => res.status === 200 || res.status === 503 });
  sleep(0.5);
}
