import http from 'k6/http';
import { check, sleep } from 'k6';

// Configuração flexível via variáveis de ambiente
const TARGET_VUS = __ENV.TARGET_VUS || 200;
const DURATION = __ENV.DURATION || '5m';
const TOKEN = __ENV.TOKEN; // Token JWT Obrigatório

export const options = {
  stages: [
    { duration: '30s', target: parseInt(TARGET_VUS) }, // Ramp-up rápido
    { duration: DURATION, target: parseInt(TARGET_VUS) }, // Hold
    { duration: '30s', target: 0 }, // Ramp-down
  ],
  thresholds: {
    http_req_duration: ['p(95)<1000'], // Latência aceitável < 1s
    http_req_failed: ['rate<0.01'],    // Erros < 1%
  },
};

export default function () {
  if (!TOKEN) {
    throw new Error('TOKEN environment variable is required');
  }

  const params = {
    headers: {
      'Authorization': `Bearer ${TOKEN}`,
      'Content-Type': 'application/json',
    },
  };

  // Alterado para /api/health para testar o Backend diretamente (pós-auth)
  // Ou /health do frontend se ele aceitar token (mas ele redireciona)
  // Melhor testar uma rota de API protegida leve, ex: /api/users/me ou continuar no /api/health se ele for protegido
  const res = http.get('https://workspace-stg.skyfirstlabs.com/api/health', params);
  
  check(res, {
    'status was 200': (r) => r.status == 200,
    'latency < 500ms': (r) => r.timings.duration < 500,
  });
  
  sleep(1);
}
