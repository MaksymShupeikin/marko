import { chromium } from 'playwright';
import fs from 'node:fs/promises';

const frontendUrl = process.env.E2E_FRONTEND_URL || 'http://frontend';
const expectedProduct = process.env.E2E_EXPECTED_PRODUCT || 'PROMPT 15.015 E2E brake pad';
const assertions = [];
const apiResponses = [];
const diagnostics = { console_errors: [], page_errors: [], request_failures: [] };
const customerJourneys = {};
const interceptedExternalSourceUrls = [];
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1100 },
  // The Playwright container can inherit LANG=C. Flutter Web passes the
  // browser locale to Intl.Locale, where "C" is invalid and aborts runApp.
  locale: 'ru-RU',
});
await context.route('https://prom.ua/**', async (route) => {
  interceptedExternalSourceUrls.push(route.request().url());
  await route.fulfill({
    status: 200,
    contentType: 'text/html; charset=utf-8',
    body: '<!doctype html><title>Intercepted Prom source</title>',
  });
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

async function visibleText(text, label, timeout = 180000) {
  // Flutter's canvas renderer exposes ordinary painted text through the
  // semantics tree as aria-labels, while real controls keep DOM text. Cover
  // both representations so the assertion observes what a user can access.
  const candidates = page
    .getByLabel(text, { exact: false })
    .or(page.getByText(text, { exact: false }));
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const count = await candidates.count();
    for (let index = 0; index < count; index += 1) {
      const candidate = candidates.nth(index);
      if (await candidate.isVisible().catch(() => false)) {
        assertions.push({ id: label, status: 'PASS', expected: text });
        return candidate;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`No visible text within ${timeout}ms: ${text}`);
}

async function visibleEnabledText(text, label, timeout = 30000) {
  const candidates = page
    .getByLabel(text, { exact: false })
    .or(page.getByText(text, { exact: false }));
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const count = await candidates.count();
    for (let index = 0; index < count; index += 1) {
      const candidate = candidates.nth(index);
      const visible = await candidate.isVisible().catch(() => false);
      const enabled = await candidate.isEnabled().catch(() => false);
      if (visible && enabled) {
        assertions.push({ id: label, status: 'PASS', expected: text });
        return candidate;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`No visible enabled text within ${timeout}ms: ${text}`);
}

async function visibleEnabledTextAfterScroll(text, label, timeout = 30000) {
  const candidates = page
    .getByLabel(text, { exact: false })
    .or(page.getByText(text, { exact: false }));
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const count = await candidates.count();
    for (let index = 0; index < count; index += 1) {
      const candidate = candidates.nth(index);
      const visible = await candidate.isVisible().catch(() => false);
      const enabled = await candidate.isEnabled().catch(() => false);
      if (visible && enabled) {
        assertions.push({ id: label, status: 'PASS', expected: text });
        return candidate;
      }
    }
    await page.mouse.wheel(0, 700);
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`No visible enabled text after scrolling within ${timeout}ms: ${text}`);
}

function completeJourney(
  id,
  startedAt,
  {
    screens,
    clicks,
    unexplained = 0,
    timeToFirstUsefulResultMs = null,
    note = null,
  },
) {
  customerJourneys[id] = {
    status: 'PASS',
    screens,
    clicks,
    unexplained,
    time_to_first_useful_result_ms:
      timeToFirstUsefulResultMs ?? Date.now() - startedAt,
    duration_ms: Date.now() - startedAt,
    note,
  };
}

async function exactVisibleText(text, timeout = 180000) {
  const candidates = page
    .getByLabel(text, { exact: true })
    .or(page.getByText(text, { exact: true }));
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const count = await candidates.count();
    for (let index = 0; index < count; index += 1) {
      const candidate = candidates.nth(index);
      if (await candidate.isVisible().catch(() => false)) return candidate;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`No visible exact text within ${timeout}ms: ${text}`);
}

async function exactVisibleTextAfterScroll(text, timeout = 30000) {
  // Flutter Web may merge a tappable InkWell and all of its descendants into
  // one accessibility label. A seller name is then visible inside that label,
  // but no exact semantic node exists for the nested Text widget.
  const candidates = page
    .getByLabel(text, { exact: false })
    .or(page.getByText(text, { exact: false }));
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const count = await candidates.count();
    for (let index = 0; index < count; index += 1) {
      const candidate = candidates.nth(index);
      if (await candidate.isVisible().catch(() => false)) return candidate;
    }
    await page.mouse.wheel(0, 700);
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`No visible exact text after scrolling for ${timeout}ms: ${text}`);
}

async function visibleDisabledPopupForText(text, timeout = 30000) {
  const candidates = page
    .getByLabel(text, { exact: false })
    .or(page.getByText(text, { exact: false }));
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const count = await candidates.count();
    for (let index = 0; index < count; index += 1) {
      const candidate = candidates.nth(index);
      if (!(await candidate.isVisible().catch(() => false))) continue;
      const attributes = await candidate.evaluate((element) => ({
        role: element.getAttribute('role'),
        disabled: element.getAttribute('aria-disabled'),
      }));
      if (attributes.role === 'menuitem' && attributes.disabled === 'true') {
        return candidate;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`No visible Flutter popup container within ${timeout}ms: ${text}`);
}

async function clickPopupRow(
  optionText,
  {
    index,
    itemCount,
    headerRows,
    label,
    timeout = 30000,
  },
) {
  const popup = await visibleDisabledPopupForText(optionText, timeout);
  const box = await popup.boundingBox();
  if (box === null) throw new Error(`Popup has no clickable bounds: ${optionText}`);
  const slotCount = itemCount + headerRows;
  const rowCenter = headerRows + index + 0.5;
  const clickX = box.x + box.width / 2;
  const clickY = box.y + (rowCenter * box.height) / slotCount;
  await page.mouse.click(clickX, clickY);
  assertions.push({
    id: label,
    status: 'PASS',
    expected: optionText,
    interaction: 'coordinate within Flutter disabled popup semantics container',
    popup_bounds: box,
    row_index: index,
  });
}

async function clickAndVerifyExternalSource(locator, expectedUrl) {
  const initialCount = interceptedExternalSourceUrls.length;
  await locator.click();
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline && interceptedExternalSourceUrls.length === initialCount) {
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  const observed = interceptedExternalSourceUrls
    .slice(initialCount)
    .find((url) => url === expectedUrl);
  if (!observed) {
    throw new Error(`Competitor source was not opened: ${expectedUrl}`);
  }
  assertions.push({
    id: 'BROWSER_COMPETITOR_SOURCE_OPENED',
    status: 'PASS',
    expected: expectedUrl,
    network_mode: 'intercepted_without_live_request',
  });
}

async function clickButton(name, timeout = 30000) {
  const button = page.getByRole('button', { name, exact: true }).first();
  await button.waitFor({ state: 'visible', timeout });
  await button.click();
}

async function enableFlutterSemantics() {
  const semantics = page.locator('flt-semantics-placeholder');
  if (await semantics.count()) {
    await semantics.evaluate((element) => element.click());
  }
}

async function navigateDashboardTab(tab) {
  await page.goto(`${frontendUrl}/#/${tab}`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  await enableFlutterSemantics();
}

async function waitForArtifactMarker(path, timeoutMs = 240000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      await fs.access(path);
      return;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  }
  throw new Error(`Timed out waiting for host marker: ${path}`);
}

async function visibleTerminalRunStatus() {
  const completed = page
    .getByLabel('Расчёт завершён', { exact: false })
    .or(page.getByText('Расчёт завершён', { exact: false }));
  const partial = page
    .getByLabel('Завершён частично', { exact: false })
    .or(page.getByText('Завершён частично', { exact: false }));
  const terminal = completed.or(partial).first();
  await terminal.waitFor({ state: 'visible', timeout: 180000 });
  assertions.push({
    id: 'BROWSER_PRICING_RUN_FINISHED',
    status: 'PASS',
    expected: 'completed|partial',
  });
}

async function waitForCsvExport(timeout) {
  return page.waitForResponse(
    (response) =>
      response.url().includes('/api/v1/pricing/recommendations/export'),
    { timeout },
  );
}

async function triggerCsvExport(label) {
  const responsePromise = waitForCsvExport(30000);
  await clickPopupRow('CSV (.csv)', {
    index: 1,
    itemCount: 2,
    headerRows: 0,
    label,
  });
  return await responsePromise;
}

async function selectUkrainianLanguage() {
  // CanvasKit does not always rematerialize a compact PopupMenuButton as an
  // ARIA node after a desktop-to-mobile viewport change. Its header hit target
  // is nevertheless deterministic in this fixed 375x812 journey: immediately
  // left of the logout button, centred in the 64px mobile header.
  const viewport = page.viewportSize();
  if (viewport === null || viewport.width !== 375 || viewport.height !== 812) {
    throw new Error(`Unexpected mobile viewport: ${JSON.stringify(viewport)}`);
  }
  await page.mouse.click(viewport.width - 111, 32);
  assertions.push({
    id: 'BROWSER_LANGUAGE_SELECTOR_TARGETED',
    status: 'PASS',
    expected: 'mobile header language hit target',
  });
  await clickPopupRow('Українська', {
    index: 1,
    itemCount: 2,
    headerRows: 1,
    label: 'BROWSER_UKRAINIAN_OPTION_SELECTED',
  });
}

try {
  const s1Started = Date.now();
  await page.goto(frontendUrl, { waitUntil: 'networkidle', timeout: 60000 });
  await enableFlutterSemantics();
  await visibleText('Сравнение цен', 'BROWSER_PAGE_RENDERED');
  await visibleText(expectedProduct, 'BROWSER_RECOMMENDATION_VISIBLE');
  const meResponse = apiResponses.find((item) => item.url.endsWith('/auth/me'));
  if (!meResponse || meResponse.status !== 200) throw new Error('E2E auth path was not observed');
  assertions.push({ id: 'BROWSER_E2E_AUTH', status: 'PASS', status_code: 200 });
  completeJourney('S-1', s1Started, {
    screens: 1,
    clicks: 0,
    unexplained: 0,
    note: 'Controlled E2E identity; /api/v1/auth/me returned HTTP 200.',
  });

  // The host intentionally stops the broker, database and workers after the
  // first eventual-render proof. Do not expand a stateful card while polling
  // is expected to replace its backing list.
  await waitForArtifactMarker('/artifacts/host-business-checks-complete');
  await navigateDashboardTab('pricing');
  await visibleText(
    expectedProduct,
    'BROWSER_RECOMMENDATION_STABLE_AFTER_FAILURES',
    30000,
  );
  // Worker-loss redelivery may legitimately change which of the two fixture
  // items receives the replay evidence. Expand the card carrying the verified
  // advisory instead of coupling the UI assertion to task completion order.
  const s4Started = Date.now();
  const advisorySummary = await visibleText(
    'ориентир, требует проверки',
    'BROWSER_CUSTOMER_TARGET_VISIBLE',
    30000,
  );
  const s4FirstResultMs = Date.now() - s4Started;
  await advisorySummary.click();
  await visibleText(
    'Ценовой ориентир заказчика',
    'BROWSER_CUSTOMER_POLICY_VISIBLE',
    30000,
  );
  await visibleText('Снизить: 98 UAH', 'BROWSER_CUSTOMER_LOWER_VISIBLE', 30000);
  await visibleText(
    'автоматически не применяется',
    'BROWSER_NO_AUTO_APPLICATION_VISIBLE',
    30000,
  );
  await visibleText('Automatic eligibility', 'BROWSER_ELIGIBILITY_VISIBLE', 30000);
  await visibleText('blocked', 'BROWSER_ELIGIBILITY_BLOCKED', 30000);
  await visibleText(
    'Ручная цена (audit)',
    'BROWSER_MANUAL_OVERRIDE_VISIBLE',
    30000,
  );
  await visibleText('Отклонить', 'BROWSER_REJECT_VISIBLE', 30000);
  const acceptButtons = await page.getByRole('button', { name: 'Принять', exact: true }).count();
  if (acceptButtons !== 0) throw new Error('Ineligible recommendation exposes Accept');
  assertions.push({ id: 'BROWSER_ACCEPT_HIDDEN', status: 'PASS', expected: 0 });
  const recommendationResponse = apiResponses.find((item) => item.url.includes('/pricing/recommendations'));
  if (!recommendationResponse || recommendationResponse.status !== 200) {
    throw new Error('Recommendation API response was not observed');
  }
  assertions.push({ id: 'BROWSER_REAL_API', status: 'PASS', status_code: 200 });
  const sourceSeller = await exactVisibleTextAfterScroll('Fixture Seller 1', 30000);
  await clickAndVerifyExternalSource(
    sourceSeller,
    'https://prom.ua/ua/p1-e2e-001.html',
  );
  completeJourney('S-4', s4Started, {
    screens: 2,
    clicks: 2,
    unexplained: 0,
    timeToFirstUsefulResultMs: s4FirstResultMs,
    note: 'Recommendation detail and competitor source; Prom URL was intercepted before network access.',
  });
  await page.screenshot({ path: '/artifacts/browser-recommendation.png', fullPage: true });

  const s6Started = Date.now();
  await page.mouse.wheel(0, -10000);
  await new Promise((resolve) => setTimeout(resolve, 300));
  const expandedAdvisory = await visibleText(
    'ориентир, требует проверки',
    'BROWSER_ADVISORY_READY_TO_COLLAPSE',
    30000,
  );
  await expandedAdvisory.click();
  let s6Clicks = 1;
  let noRecommendationReasonFound = false;
  for (const productName of [
    expectedProduct,
    'PROMPT 15.015 missing evidence brake pad',
  ]) {
    const productCard = await exactVisibleTextAfterScroll(productName, 30000);
    await productCard.click();
    s6Clicks += 1;
    const reasons = page
      .getByLabel('мало валидных конкурентов', { exact: false })
      .or(page.getByText('мало валидных конкурентов', { exact: false }));
    let reasonVisible = false;
    const reasonDeadline = Date.now() + 3000;
    while (Date.now() < reasonDeadline && !reasonVisible) {
      const reasonCount = await reasons.count();
      for (let index = 0; index < reasonCount; index += 1) {
        if (await reasons.nth(index).isVisible().catch(() => false)) {
          reasonVisible = true;
          break;
        }
      }
      if (!reasonVisible) {
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
    }
    if (reasonVisible) {
      assertions.push({
        id: 'BROWSER_NO_RECOMMENDATION_REASON_VISIBLE',
        status: 'PASS',
        expected: 'мало валидных конкурентов',
        product: productName,
      });
      noRecommendationReasonFound = true;
      break;
    }
    await productCard.click();
    s6Clicks += 1;
  }
  if (!noRecommendationReasonFound) {
    throw new Error('No-recommendation reason was not visible on either fixture card');
  }
  completeJourney('S-6', s6Started, {
    screens: 1,
    clicks: s6Clicks,
    unexplained: 0,
    note: 'The insufficient-data position exposes the translated TOO_FEW_COMPETITORS reason.',
  });

  const s2Started = Date.now();
  await navigateDashboardTab('catalog');
  await visibleText('Каталог Prom.ua', 'BROWSER_CATALOG_PAGE_VISIBLE', 30000);
  await clickButton('Импорт XLSX');
  await visibleText(
    'Выберите выгрузку Prom.ua',
    'BROWSER_IMPORT_DIALOG_VISIBLE',
    30000,
  );
  const fileChooserPromise = page.waitForEvent('filechooser', { timeout: 30000 });
  await clickButton('Выбрать XLSX');
  const fileChooser = await fileChooserPromise;
  await fileChooser.setFiles('/artifacts/ui-catalog-fixture.xlsx');
  const sheetPicker = page
    .getByRole('button', { name: 'Лист каталога', exact: true })
    .or(page.getByText('Лист каталога', { exact: true }))
    .first();
  await sheetPicker.waitFor({ state: 'visible', timeout: 30000 });
  await sheetPicker.click();
  await (await exactVisibleText('Catalog · 3 строк', 30000)).click();
  assertions.push({
    id: 'BROWSER_CATALOG_SHEET_SELECTED',
    status: 'PASS',
    expected: 'Catalog',
  });
  await clickButton('Импортировать');
  await visibleText(
    'Каталог импортирован частично',
    'BROWSER_CATALOG_IMPORT_PARTIAL',
  );
  await visibleText(
    'Записано 2 из 3; отклонено 1.',
    'BROWSER_CATALOG_IMPORT_COUNTS',
  );
  completeJourney('S-2', s2Started, {
    screens: 2,
    clicks: 6,
    unexplained: 0,
    note: 'Catalog page plus import dialog; partial result reports 2 imported and 1 rejected row.',
  });
  await page.screenshot({ path: '/artifacts/browser-catalog-import.png', fullPage: true });
  await clickButton('Готово');

  const s5Started = Date.now();
  await navigateDashboardTab('pricing');
  await (
    await visibleEnabledText(
      'Макс. изменение цены',
      'BROWSER_IMPORTANCE_SORT_CONTROL_VISIBLE',
      30000,
    )
  ).click();
  await clickPopupRow('Макс. изменение, %', {
    index: 1,
    itemCount: 5,
    headerRows: 1,
    label: 'BROWSER_IMPORTANCE_SORT_OPTION_SELECTED',
  });
  await visibleText(
    'Макс. изменение, %',
    'BROWSER_IMPORTANCE_SORT_APPLIED',
    30000,
  );
  const exportControl = await visibleEnabledText(
    'Экспорт',
    'BROWSER_EXPORT_CONTROL_VISIBLE',
    30000,
  );
  await exportControl.click();
  const exportResponse = await triggerCsvExport('BROWSER_EXPORT_CSV_SELECTED');
  if (exportResponse.status() !== 200) {
    throw new Error(`UI recommendation export returned HTTP ${exportResponse.status()}`);
  }
  const exportBytes = await exportResponse.body();
  const exportDisposition = exportResponse.headers()['content-disposition'] || '';
  if (exportBytes.length <= 0 || !exportDisposition.toLowerCase().includes('.csv')) {
    throw new Error('UI recommendation export response is not a non-empty CSV');
  }
  const exportText = new TextDecoder('utf-8').decode(exportBytes);
  if (
    !exportText.includes('customer_advisory_action') ||
    !exportText.includes('customer_advisory_price') ||
    !exportText.includes('LOWER') ||
    !exportText.includes('98 UAH') ||
    !exportText.includes('false')
  ) {
    throw new Error('UI recommendation export omitted the gated customer target');
  }
  await fs.writeFile('/artifacts/ui-recommendations.csv', exportBytes);
  assertions.push({
    id: 'BROWSER_EXPORT_DOWNLOADED',
    status: 'PASS',
    bytes: exportBytes.length,
    content_disposition: exportDisposition,
  });
  assertions.push({
    id: 'BROWSER_CUSTOMER_TARGET_EXPORTED',
    status: 'PASS',
    expected: 'LOWER 98 UAH; automatic_price_application=false',
  });
  completeJourney('S-5', s5Started, {
    screens: 1,
    clicks: 4,
    unexplained: 0,
    note: 'Sorted by percentage price deviation and exported the resulting queue as CSV.',
  });

  const s3Started = Date.now();
  await page.setViewportSize({ width: 375, height: 812 });
  await clickButton('Запустить');
  await visibleText('Запустить расчёт цен?', 'BROWSER_PRICING_CONFIRM_VISIBLE');
  const uiRunResponsePromise = page.waitForResponse(
    (response) => response.url().includes('/api/v1/e2e/pricing/runs'),
    { timeout: 30000 },
  );
  await page.getByRole('button', { name: 'Запустить', exact: true }).last().click();
  const uiRunResponse = await uiRunResponsePromise;
  if (uiRunResponse.status() !== 202) {
    throw new Error(`UI pricing run returned HTTP ${uiRunResponse.status()}`);
  }
  const uiRun = await uiRunResponse.json();
  await fs.writeFile(
    '/artifacts/ui-pricing-run.json',
    JSON.stringify({ run_id: uiRun.id }, null, 2),
  );
  assertions.push({
    id: 'BROWSER_PRICING_RUN_ACCEPTED',
    status: 'PASS',
    run_id: uiRun.id,
  });
  assertions.push({
    id: 'BROWSER_PRICING_RUN_STARTED',
    status: 'PASS',
    expected: 'HTTP 202 with stable run id',
  });
  await visibleTerminalRunStatus();
  completeJourney('S-3', s3Started, {
    screens: 2,
    clicks: 2,
    unexplained: 0,
    note: 'Start confirmation and terminal completed/partial state; shared with S-8.',
  });
  completeJourney('S-8', s3Started, {
    screens: 2,
    clicks: 2,
    unexplained: 0,
    note: 'The S-3 pricing run was executed at the measured 375x812 viewport.',
  });
  await page.screenshot({ path: '/artifacts/browser-mobile-run.png', fullPage: true });

  const s7Started = Date.now();
  let s7Clicks = 2;
  await selectUkrainianLanguage();
  await visibleText('Порівняння цін', 'BROWSER_UKRAINIAN_LOCALE');
  await visibleText('Експорт', 'BROWSER_UKRAINIAN_EXPORT');
  const ukrainianPolicyCandidates = page
    .getByLabel('Ціновий орієнтир замовника', { exact: false })
    .or(page.getByText('Ціновий орієнтир замовника', { exact: false }));
  let ukrainianPolicy = null;
  const ukrainianPolicyCount = await ukrainianPolicyCandidates.count();
  for (let index = 0; index < ukrainianPolicyCount; index += 1) {
    const candidate = ukrainianPolicyCandidates.nth(index);
    if (await candidate.isVisible().catch(() => false)) {
      ukrainianPolicy = candidate;
      break;
    }
  }
  if (ukrainianPolicy === null) {
    const ukrainianRecommendation = await exactVisibleTextAfterScroll(
      'орієнтир, потребує перевірки',
      30000,
    );
    assertions.push({
      id: 'BROWSER_UKRAINIAN_RECOMMENDATION_VISIBLE',
      status: 'PASS',
      expected: 'орієнтир, потребує перевірки',
    });
    await ukrainianRecommendation.click();
    s7Clicks += 1;
    ukrainianPolicy = await visibleText(
      'Ціновий орієнтир замовника',
      'BROWSER_UKRAINIAN_RECOMMENDATION_DETAIL',
      30000,
    );
  } else {
    assertions.push({
      id: 'BROWSER_UKRAINIAN_RECOMMENDATION_DETAIL',
      status: 'PASS',
      expected: 'Ціновий орієнтир замовника',
    });
  }
  await clickAndVerifyExternalSource(
    await exactVisibleTextAfterScroll('Fixture Seller 1', 30000),
    'https://prom.ua/ua/p1-e2e-001.html',
  );
  s7Clicks += 1;
  // Reloading the route is an explicit screen transition in this journey and
  // collapses the very long evidence payload before exercising the toolbar.
  // A fixed wheel delta is not deterministic at the 375px viewport because
  // structured OE evidence can make the expanded card tens of thousands of
  // pixels tall.
  await page.reload({ waitUntil: 'networkidle', timeout: 60000 });
  await enableFlutterSemantics();
  await visibleText(
    'Порівняння цін',
    'BROWSER_UKRAINIAN_LOCALE_PERSISTED_AFTER_RELOAD',
  );
  await (
    await visibleEnabledTextAfterScroll(
      'Макс. зміна ціни',
      'BROWSER_UKRAINIAN_SORT_CONTROL_VISIBLE',
      30000,
    )
  ).click();
  await clickPopupRow('Макс. зміна, %', {
    index: 1,
    itemCount: 5,
    headerRows: 1,
    label: 'BROWSER_UKRAINIAN_SORT_OPTION_SELECTED',
  });
  await visibleText(
    'Макс. зміна, %',
    'BROWSER_UKRAINIAN_IMPORTANCE_SORT_APPLIED',
    30000,
  );
  s7Clicks += 2;
  await page.mouse.wheel(0, -10000);
  await new Promise((resolve) => setTimeout(resolve, 300));
  const ukrainianExport = await visibleEnabledText(
    'Експорт',
    'BROWSER_UKRAINIAN_EXPORT_CONTROL_VISIBLE',
    30000,
  );
  await ukrainianExport.click();
  const ukrainianExportResponse = await triggerCsvExport(
    'BROWSER_UKRAINIAN_CSV_SELECTED',
  );
  if (ukrainianExportResponse.status() !== 200) {
    throw new Error(
      `Ukrainian UI recommendation export returned HTTP ${ukrainianExportResponse.status()}`,
    );
  }
  s7Clicks += 2;
  completeJourney('S-7', s7Started, {
    screens: 2,
    clicks: s7Clicks,
    unexplained: 0,
    note: 'Repeated recommendation/source verification, importance sort and CSV export in Ukrainian.',
  });
  await page.screenshot({ path: '/artifacts/browser-mobile-uk.png', fullPage: true });

  await fs.writeFile(
    '/artifacts/browser-assertions.json',
    JSON.stringify(
      {
        status: 'PASS',
        assertions,
        customer_journeys: customerJourneys,
        intercepted_external_source_urls: interceptedExternalSourceUrls,
        api_responses: apiResponses,
        diagnostics,
      },
      null,
      2,
    ),
  );
  process.stdout.write(
    `${JSON.stringify({
      status: 'PASS',
      assertions,
      customer_journeys: customerJourneys,
      intercepted_external_source_urls: interceptedExternalSourceUrls,
    })}\n`,
  );
} catch (error) {
  await page.screenshot({ path: '/artifacts/browser-failure.png', fullPage: true }).catch(() => {});
  const result = {
    status: 'FAIL',
    error: String(error),
    page_url: page.url(),
    assertions,
    customer_journeys: customerJourneys,
    intercepted_external_source_urls: interceptedExternalSourceUrls,
    api_responses: apiResponses,
    diagnostics,
  };
  await fs.writeFile('/artifacts/browser-assertions.json', JSON.stringify(result, null, 2));
  process.stderr.write(`${JSON.stringify(result)}\n`);
  process.exitCode = 1;
} finally {
  await browser.close();
}
