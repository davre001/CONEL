// Repository-owned acceptance fixture. Model edits cannot modify scripts/ or manifests.
// Exercise the real route handlers over loopback HTTP, with Stripe replaced by a local fixture.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { GET } from '../app/api/health/route.ts';
import { POST } from '../app/api/checkout/route.ts';

const endpoint = process.env.CONEL_VERIFY_ENDPOINT || '/api/checkout';
const method = process.env.CONEL_VERIFY_METHOD || 'POST';
if (!((endpoint === '/api/health' && ['GET', 'HEAD'].includes(method))
    || (endpoint === '/api/checkout' && method === 'POST'))) {
  console.error('No independent fixture for this endpoint and method.');
  process.exit(2);
}
const originalFetch = globalThis.fetch;
const names = ['STRIPE_SECRET_KEY', 'DEMO_STORE_URL', 'CONEL_API_URL', 'DEMO_STORE_PROJECT_ID', 'DEMO_STORE_MONITOR_KEY'];
const previous = Object.fromEntries(names.map(name => [name, process.env[name]]));
for (const name of names) delete process.env[name];
process.env.STRIPE_SECRET_KEY = 'sk_test_conel_fixture';
process.env.DEMO_STORE_URL = 'https://store.example.test';
let checkoutCalls = 0;
globalThis.fetch = async (url, options) => {
  assert.equal(String(url), 'https://api.stripe.com/v1/checkout/sessions');
  assert.equal(options.method, 'POST');
  const payload = new URLSearchParams(options.body);
  assert.equal(payload.get('line_items[0][price_data][unit_amount]'), '4900');
  assert.equal(payload.get('line_items[0][price_data][currency]'), 'usd');
  checkoutCalls++;
  return Response.json({ url: 'https://checkout.example.test/session' });
};
const server = createServer(async (request, response) => {
  try {
    const result = request.url === '/api/health' ? await GET() : await POST();
    response.writeHead(result.status, { 'Content-Type': 'application/json' });
    response.end(request.method === 'HEAD' ? undefined : await result.text());
  } catch {
    response.writeHead(500); response.end();
  }
});
try {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = 'http://127.0.0.1:' + server.address().port;
  const result = await originalFetch(origin + endpoint, { method, signal: AbortSignal.timeout(10000) });
  assert.equal(result.status, 200, 'The incident endpoint must return HTTP 200');
  if (endpoint === '/api/checkout') {
    assert.equal((await result.json()).url, 'https://checkout.example.test/session');
    assert.equal(checkoutCalls, 1);
  }
  console.log(JSON.stringify({ endpoint, method, status: result.status, fixture: 'isolated Stripe fixture; no payment or external request' }));
} catch {
  console.error('Targeted HTTP acceptance assertion failed.');
  process.exitCode = 1;
} finally {
  await new Promise(resolve => server.close(resolve));
  globalThis.fetch = originalFetch;
  for (const name of names) {
    if (previous[name] === undefined) delete process.env[name];
    else process.env[name] = previous[name];
  }
}
