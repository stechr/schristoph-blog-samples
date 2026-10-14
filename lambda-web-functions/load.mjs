// Fires N concurrent requests at one route of a running server and reports
// how long the whole batch took. Usage:
//   node load.mjs [baseUrl] [route] [concurrency]
//   node load.mjs http://localhost:3000 "/wait?ms=500" 50
const base = process.argv[2] || 'http://localhost:3000';
const route = process.argv[3] || '/wait?ms=500';
const n = Number(process.argv[4] || 50);

const started = performance.now();
const results = await Promise.all(
  Array.from({ length: n }, () => fetch(base + route).then((r) => r.status))
);
const elapsed = Math.round(performance.now() - started);
const ok = results.filter((s) => s === 200).length;
console.log(JSON.stringify({ route, concurrency: n, ok, batchMs: elapsed }));
