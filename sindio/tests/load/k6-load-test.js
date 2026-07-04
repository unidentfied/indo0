import { check } from 'k6';
import http from 'k6/http';

// ── Configuration ──────────────────────────────────────────────
export const options = {
  stages: [
    { duration: '1m', target: 50 },   // Ramp up to 50 VU
    { duration: '3m', target: 200 },  // Ramp to 200 VU
    { duration: '2m', target: 500 },  // Ramp to 500 VU (stress test)
    { duration: '2m', target: 200 },  // Ramp down
    { duration: '1m', target: 0 },    // Cool down
  ],
  thresholds: {
    http_req_duration: ['p(95)<2000'], // 95% under 2s
    http_req_failed: ['rate<0.05'],    // <5% errors
    http_reqs: ['rate>100'],            // >100 RPS
  },
};

const BASE_URL = __ENV.API_URL || 'http://localhost:8080';

// ── Test Scenarios ───────────────────────────────────────────────
export default function () {
  const endpoints = [
    { method: 'GET', url: '/health' },
    { method: 'GET', url: '/api/dashboard/metrics?system=power' },
    { method: 'GET', url: '/api/dashboard/alerts?limit=5' },
    { method: 'GET', url: '/api/infrastructure/power' },
    { method: 'GET', url: '/api/simulations/status' },
    { method: 'GET', url: '/api/v1/monitor/stress' },
    { method: 'GET', url: '/api/v1/monitor/types' },
    { method: 'POST', url: '/api/simulations/run?network=power' },
  ];

  for (const ep of endpoints) {
    const url = `${BASE_URL}${ep.url}`;
    const response = ep.method === 'POST'
      ? http.post(url, null, { headers: { 'Content-Type': 'application/json' } })
      : http.get(url);

    check(response, {
      [`${ep.method} ${ep.url} status is 200`]: (r) => r.status === 200,
      [`${ep.method} ${ep.url} response time < 2s`]: (r) => r.timings.duration < 2000,
    });

    // Rate limit between requests (simulating real user behavior)
    if (Math.random() < 0.3) {
      sleep(Math.random() * 2);
    }
  }
}

function sleep(duration) {
  const start = Date.now();
  while (Date.now() - start < duration * 1000) { /* busy wait */ }
}
