import { chromium } from 'playwright';
import fs from 'node:fs/promises';

const frontendUrl = process.env.E2E_FRONTEND_URL || 'http://frontend';
const expectedProduct = process.env.E2E_EXPECTED_PRODUCT || 'PROMPT 15.015 E2E brake pad';
const assertions = [];
const apiResponses = [];
const diagnostics = { console_errors: [], page_errors: [], request_failures: [] };
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1100 },
  // The Playwright container can inherit LANG=C. Flutter Web passes the
  // browser locale to Intl.Locale, where "C" is invalid and aborts runApp.
  locale: 'ru-RU',
});
const page = await context.newPage();
page.on('console', (message) => {
  if (message.type() === 'error') diagnostics.console_errors.push(message.text());
});
page.on('pageerror', (error) => diagnostics.page_errors.push(error.stack || String(error)));
page.on('requestfailed', (request) => {
  diagnostics.request_failures.push({
    url: request.url(),
    error: request.failure()?.errorText || 'unknown',
  });
});
page.on('response', async (response) => {
  const url = response.url();
  if (url.includes('/api/v1/')) {
    apiResponses.push({ url: new URL(url).pathname, status: response.status() });
  }
});

async function visibleText(text, label) {
  // Flutter's canvas renderer exposes ordinary painted text through the
  // semantics tree as aria-labels, while real controls keep DOM text. Cover
  // both representations so the assertion observes what a user can access.
  const locator = page
    .getByLabel(text, { exact: false })
    .or(page.getByText(text, { exact: false }))
    .first();
  await locator.waitFor({ state: 'visible', timeout: 180000 });
  assertions.push({ id: label, status: 'PASS', expected: text });
  return locator;
}

try {
  await page.goto(frontendUrl, { waitUntil: 'networkidle', timeout: 60000 });
  const semantics = page.locator('flt-semantics-placeholder');
  if (await semantics.count()) {
    await semantics.evaluate((element) => element.click());
  }
  await visibleText('Какую цену поставить сейчас', 'BROWSER_PAGE_RENDERED');
  const product = await visibleText(expectedProduct, 'BROWSER_RECOMMENDATION_VISIBLE');
  await product.click();
  await visibleText('автоцена не сформирована', 'BROWSER_ABSTENTION_VISIBLE');
  await visibleText('Automatic eligibility', 'BROWSER_ELIGIBILITY_VISIBLE');
  await visibleText('blocked', 'BROWSER_ELIGIBILITY_BLOCKED');
  await visibleText('Ручная цена (audit)', 'BROWSER_MANUAL_OVERRIDE_VISIBLE');
  await visibleText('Отклонить', 'BROWSER_REJECT_VISIBLE');
  const acceptButtons = await page.getByRole('button', { name: 'Принять', exact: true }).count();
  if (acceptButtons !== 0) throw new Error('Ineligible recommendation exposes Accept');
  assertions.push({ id: 'BROWSER_ACCEPT_HIDDEN', status: 'PASS', expected: 0 });
  const meResponse = apiResponses.find((item) => item.url.endsWith('/auth/me'));
  if (!meResponse || meResponse.status !== 200) throw new Error('E2E auth path was not observed');
  assertions.push({ id: 'BROWSER_E2E_AUTH', status: 'PASS', status_code: 200 });
  const recommendationResponse = apiResponses.find((item) => item.url.includes('/pricing/recommendations'));
  if (!recommendationResponse || recommendationResponse.status !== 200) {
    throw new Error('Recommendation API response was not observed');
  }
  assertions.push({ id: 'BROWSER_REAL_API', status: 'PASS', status_code: 200 });
  await page.screenshot({ path: '/artifacts/browser-recommendation.png', fullPage: true });
  await fs.writeFile(
    '/artifacts/browser-assertions.json',
    JSON.stringify(
      { status: 'PASS', assertions, api_responses: apiResponses, diagnostics },
      null,
      2,
    ),
  );
  process.stdout.write(`${JSON.stringify({ status: 'PASS', assertions })}\n`);
} catch (error) {
  await page.screenshot({ path: '/artifacts/browser-failure.png', fullPage: true }).catch(() => {});
  const result = {
    status: 'FAIL',
    error: String(error),
    assertions,
    api_responses: apiResponses,
    diagnostics,
  };
  await fs.writeFile('/artifacts/browser-assertions.json', JSON.stringify(result, null, 2));
  process.stderr.write(`${JSON.stringify(result)}\n`);
  process.exitCode = 1;
} finally {
  await browser.close();
}
