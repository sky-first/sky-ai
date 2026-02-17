import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '2m', target: 200 }, // Ramp to 200 (previous max)
    { duration: '5m', target: 500 }, // Ramp to 500 (Break Point)
    { duration: '2m', target: 600 }, // Push beyond
    { duration: '1m', target: 0 },   // Scale down
  ],
  thresholds: {
    http_req_duration: ['p(95)<1000'], // Expect degradation but track it
    http_req_failed: ['rate<0.05'],    // Allow 5% errors
  },
};

export default function () {
  const res = http.get('https://workspace-stg.skyfirstlabs.com/health');
  check(res, { 'status was 200': (r) => r.status == 200 });
  sleep(1);
}
