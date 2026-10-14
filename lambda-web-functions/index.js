// A plain Express server. Nothing in here is Lambda-specific except reading the
// listen address from AWS_LAMBDA_HTTP_ENDPOINT, which Lambda Web Functions set
// to "host:port". Locally the fallback is localhost:3000.
import express from 'express';

const app = express();
const [host, port] = (process.env.AWS_LAMBDA_HTTP_ENDPOINT || 'localhost:3000').split(':');

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const clamp = (value, max) => Math.min(Math.max(Number(value) || 0, 0), max);

app.get('/', (req, res) => {
  res.json({ message: 'Hello from an unmodified Express app' });
});

// Stands in for a route that mostly waits: a database query, a downstream API,
// or a model call. The event loop is free while the timer runs.
app.get('/wait', async (req, res) => {
  const ms = clamp(req.query.ms ?? 500, 10000);
  const started = Date.now();
  await sleep(ms);
  res.json({ route: 'wait', requestedMs: ms, tookMs: Date.now() - started });
});

// Stands in for a route that burns CPU synchronously. While it spins, every
// other request in the same process waits.
app.get('/cpu', (req, res) => {
  const ms = clamp(req.query.ms ?? 50, 2000);
  const end = Date.now() + ms;
  let spins = 0;
  while (Date.now() < end) spins++;
  res.json({ route: 'cpu', busyMs: ms, spins });
});

app.listen(Number(port), host, () => {
  console.log(`listening on ${host}:${port}`);
});
