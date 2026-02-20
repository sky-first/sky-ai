import http from 'k6/http';
import { check, sleep } from 'k6';

export let options = {
    stages: [
        { duration: '30s', target: 20 },  // Warm up: 0 a 20 usuários
        { duration: '1m', target: 50 },   // Load: manter 50 usuários
        { duration: '1m', target: 100 },  // Stress: subir para 100
        { duration: '1m', target: 200 },  // Breaking: tentar 200
        { duration: '30s', target: 0 },   // Ramp down
    ],
    thresholds: {
        http_req_failed: ['rate<0.01'],   // Falha menor que 1%
        http_req_duration: ['p(95)<500'], // 95% das reqs abaixo de 500ms
    },
};

export default function () {
    let res = http.get('http://sky-be-stg-common-app.staging.svc.cluster.local/health');
    check(res, {
        'status is 200': (r) => r.status === 200,
    });
    sleep(1);
}
