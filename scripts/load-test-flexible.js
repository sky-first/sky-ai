import http from 'k6/http';
import { check, sleep } from 'k6';

// Configuração flexível via variáveis de ambiente
const TARGET_VUS = __ENV.TARGET_VUS || 200;
const DURATION = __ENV.DURATION || '5m';

export const options = {
  stages: [
    { duration: '1m', target: parseInt(TARGET_VUS) }, // Ramp-up
    { duration: DURATION, target: parseInt(TARGET_VUS) }, // Hold
    { duration: '30s', target: 0 }, // Ramp-down
  ],
  thresholds: {
    http_req_duration: ['p(95)<2000'], // SSR pode ser mais lento, aceitando < 2s
    http_req_failed: ['rate<0.05'],    // Erros < 5%
  },
};

export default function () {
  // Pivot para /login (SSR) para gerar carga de CPU no Frontend e tráfego no Ingress
  // Bypassing Auth requirement do /health
  const res = http.get('https://workspace-stg.skyfirstlabs.com/login');
  
  check(res, {
    'status was 200': (r) => r.status == 200,
    // Verificação de conteúdo para garantir que renderizou a página
    'content loaded': (r) => r.body && r.body.length > 0,
  });
  
  sleep(1);
}
