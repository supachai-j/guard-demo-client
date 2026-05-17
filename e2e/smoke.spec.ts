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
