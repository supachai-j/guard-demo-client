import { test, expect, type Page } from '@playwright/test';

// Backdoor login — UI has admin/admin defaults but typing them is flakier
// than just stamping the JWT we already trust into localStorage. The token
// path mirrors what the Login form does on success.
async function loginAs(page: Page, user = 'admin', pass = 'admin') {
  const resp = await page.request.post('http://localhost:8000/api/auth/login', {
    data: { username: user, password: pass },
  });
  expect(resp.ok()).toBeTruthy();
  const { access_token } = await resp.json();
  await page.goto('/');
  await page.evaluate((t) => localStorage.setItem('admin_token', t), access_token);
}

test('1. unauthenticated /admin redirects to /login', async ({ page }) => {
  await page.goto('/admin');
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByRole('heading', { name: /admin sign in/i })).toBeVisible();
});

test('2. login flow with admin/admin lands on /admin', async ({ page }) => {
  await page.goto('/login');
  // The form defaults username="admin"; the <label>s aren't htmlFor-linked
  // to the inputs (no id), so target by autocomplete + input type.
  await page.locator('input[autocomplete="username"]').fill('admin');
  await page.locator('input[type="password"]').fill('admin');
  await page.getByRole('button', { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/admin/, { timeout: 10_000 });
  await expect(page.getByRole('button', { name: /threat lab/i })).toBeVisible({ timeout: 10_000 });
});

test('3. Threat Lab → Playbooks panel loads with playbook options', async ({ page }) => {
  await loginAs(page);
  await page.goto('/admin');
  await page.getByRole('button', { name: /threat lab/i }).click();
  await page.getByRole('button', { name: /playbooks/i }).click();
  // The panel renders a Playbook label + select even before clicking Run.
  await expect(page.getByText(/^Playbook$/)).toBeVisible({ timeout: 10_000 });
  // Built-in playbooks (OWASP, POC) populate the catalog endpoint.
  const playbooks = await page.request.get('http://localhost:8000/api/playbooks');
  const data = await playbooks.json();
  expect(data.playbooks.length).toBeGreaterThan(0);
});

test('4. Threat Lab → Cost panel renders aggregates from /api/audit/cost-summary', async ({ page }) => {
  await loginAs(page);
  await page.goto('/admin');
  await page.getByRole('button', { name: /threat lab/i }).click();
  await page.getByRole('button', { name: /^cost$/i }).click();
  // The summary card always renders once /api/audit/cost-summary resolves
  // (even with $0.00 in a fresh DB), proving the panel mounted end-to-end.
  await expect(page.getByText(/Total cost \(est\.\)/i)).toBeVisible({ timeout: 10_000 });
});

test('5. landing page chat widget opens and accepts input', async ({ page }) => {
  // Pure UI smoke — no LLM call. Validates the demo's main affordance
  // (the floating chat bubble) without needing any provider credentials.
  await page.goto('/');
  // The collapsed bubble button contains a Lucide MessageCircle SVG. It's
  // wrapped in a div.fixed so we can't use button.fixed directly.
  await page.locator('div.fixed.bottom-4.right-4 > button').click();
  const textarea = page.getByPlaceholder(/type a message/i);
  await expect(textarea).toBeVisible({ timeout: 5_000 });
  await textarea.fill('hello');
  // The send button (Send icon) sits adjacent to the textarea and enables
  // once the textarea has non-empty content.
  const sendButton = textarea.locator('xpath=ancestor::div[contains(@class,"flex")]/button').first();
  await expect(sendButton).toBeEnabled();
});

test('6. custom playbook CRUD via API (create → list → delete)', async ({ page }) => {
  await loginAs(page);
  const token = await page.evaluate(() => localStorage.getItem('admin_token'));
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  // Create.
  const name = `e2e-smoke-${Date.now()}`;
  const create = await page.request.post('http://localhost:8000/api/playbooks', {
    headers,
    data: {
      name,
      description: 'e2e smoke',
      prompts: [{ id: 'p1', category: 'Custom', prompt: 'hi', expected: 'allowed' }],
    },
  });
  expect(create.ok()).toBeTruthy();
  const { id } = await create.json();
  expect(id).toBeTruthy();

  // List confirms it's there.
  const list = await page.request.get('http://localhost:8000/api/playbooks');
  const { playbooks } = await list.json();
  expect(playbooks.some((p: any) => p.id === id)).toBeTruthy();

  // Delete + verify gone.
  const del = await page.request.delete(`http://localhost:8000/api/playbooks/${id}`, { headers });
  expect(del.ok()).toBeTruthy();
  const after = await page.request.get('http://localhost:8000/api/playbooks');
  const { playbooks: remaining } = await after.json();
  expect(remaining.some((p: any) => p.id === id)).toBeFalsy();
});

test('8. MCP connector — capabilities + disabled-tools PATCH round-trip', async ({ page }) => {
  // Verifies the new Connector Management surface: register an MCP server,
  // ask for its capabilities (empty until discovery runs — but the endpoint
  // still returns the disabled_tools field), then PATCH the deny list and
  // confirm the canonical state via GET.
  await loginAs(page);
  const token = await page.evaluate(() => localStorage.getItem('admin_token'));
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const name = `e2e-mcp-${Date.now()}`;
  const create = await page.request.post('http://localhost:8000/api/tools', {
    headers,
    data: { name, type: 'mcp', endpoint: 'http://127.0.0.1:9999/mcp', enabled: true, description: 'e2e smoke' },
  });
  expect(create.ok()).toBeTruthy();
  const { id } = await create.json();

  try {
    // GET before any discovery: tools list empty, deny list empty.
    const beforeResp = await page.request.get(`http://localhost:8000/api/tools/${id}/capabilities`, { headers });
    expect(beforeResp.ok()).toBeTruthy();
    const before = await beforeResp.json();
    expect(before.disabled_tools).toEqual([]);
    expect(Array.isArray(before.tools)).toBeTruthy();

    // PATCH a deny list (server doesn't require the name to exist in
    // discovery — operator may add it ahead of time).
    const patch = await page.request.patch(`http://localhost:8000/api/tools/${id}/disabled-tools`, {
      headers,
      data: { disabled: ['search_web', 'send_email', 'search_web'] }, // dup is dedup-ed
    });
    expect(patch.ok()).toBeTruthy();
    expect((await patch.json()).disabled_tools).toEqual(['search_web', 'send_email']);

    // GET again confirms persistence + dedup ordering preserved.
    const after = await (await page.request.get(`http://localhost:8000/api/tools/${id}/capabilities`, { headers })).json();
    expect(after.disabled_tools).toEqual(['search_web', 'send_email']);
  } finally {
    await page.request.delete(`http://localhost:8000/api/tools/${id}`, { headers });
  }
});

test('7. SSE audit stream emits hello handshake', async ({ page }) => {
  // The EventSource endpoint takes the JWT as a query param (browsers can't
  // attach Authorization headers to EventSource). The `hello` event fires
  // on subscribe, before any audit row exists — so this is deterministic in
  // CI without needing a configured guardrail.
  await loginAs(page);
  await page.goto('/admin');
  const helloData = await page.evaluate(async () => {
    const token = localStorage.getItem('admin_token');
    return new Promise<string>((resolve, reject) => {
      const es = new EventSource(`/api/audit/stream?token=${token}&flagged_only=false`);
      es.addEventListener('hello', (e: MessageEvent) => {
        es.close();
        resolve(e.data);
      });
      es.addEventListener('error', () => {
        es.close();
        reject(new Error('EventSource error'));
      });
      setTimeout(() => { es.close(); reject(new Error('timeout')); }, 8_000);
    });
  });
  expect(helloData).toMatch(/subscribers/);
});
