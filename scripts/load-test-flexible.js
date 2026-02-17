import http from 'k6/http';
import { check, sleep } from 'k6';

// Configuração flexível via variáveis de ambiente
const TARGET_VUS = __ENV.TARGET_VUS || 200;
const DURATION = __ENV.DURATION || '5m';

export const options = {
  stages: [
    { duration: '2m', target: parseInt(TARGET_VUS) }, // Ramp-up
    { duration: DURATION, target: parseInt(TARGET_VUS) }, // Hold
    { duration: '1m', target: 0 }, // Ramp-down
  ],
  thresholds: {
    http_req_duration: ['p(95)<1000'], // Latência aceitável < 1s
    http_req_failed: ['rate<0.01'],    // Erros < 1%
  },
};

export default function () {
  const res = http.get('https://workspace-stg.skyfirstlabs.com/health');
  
  check(res, {
    'status was 200': (r) => r.status == 200,
    'latency < 500ms': (r) => r.timings.duration < 500,
  });
  
  sleep(1);
}
