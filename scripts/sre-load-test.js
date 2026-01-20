import http from 'k6/http';
import { check, sleep, group } from 'k6';

// Test Configurations via Environment Variables
// Direct IP access as configured previously
const BASE_URL_FRONTEND = __ENV.BASE_URL_FRONTEND || 'http://135.18.146.170';
const BASE_URL_BACKEND = __ENV.BASE_URL_BACKEND || 'http://135.18.146.170/api';

export const options = {
  thresholds: {
    http_req_failed: ['rate<0.01'], // http errors should be less than 1%
    http_req_duration: ['p(95)<500'], // 95% of requests should be below 500ms
  },
  stages: [
    { duration: '30s', target: 50 },  // ramp-up to 50 users
    { duration: '1m', target: 100 }, // ramp-up to 100 users
    { duration: '1m', target: 200 }, // spike to 200 users
    { duration: '1m', target: 200 }, // stay at 200 users
    { duration: '30s', target: 0 },   // ramp-down to 0 users
  ],
};

export default function () {
  group('Frontend Page Load', function () {
    const res = http.get(`${BASE_URL_FRONTEND}/login`);
    check(res, {
      'Frontend is 200': (r) => r.status === 200,
    });
  });

  group('Backend Health Check', function () {
    const res = http.get(`${BASE_URL_BACKEND}/v1/health`);
    check(res, {
      'Backend is 200 or 401': (r) => r.status === 200 || r.status === 401,
    });
  });

  sleep(1);
}
