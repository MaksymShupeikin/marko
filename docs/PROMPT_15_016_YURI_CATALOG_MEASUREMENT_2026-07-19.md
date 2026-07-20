# PROMPT 15.016 — измерение реального каталога Юрия

## 1. Статус

- **Catalog measurement:** `PASS`.
- **Requirement R-15:** `PASS` для измерения client workbook.
- **Representative market replay:** не входил в этот этап и остаётся `BLOCKED_AUTHORITY_DATA`.
- **Controlled pilot / production:** не авторизованы.

## 2. Provenance

| Поле | Значение |
|---|---|
| Источник | Client-provided Prom.ua XLSX `2_5370668612929495405.xlsx` |
| Получен | 2026-07-19, прямо от пользователя в этой задаче |
| Source SHA-256 | `7871f6b20b21d96bbd7b5c2ea8c951c2144a6adec04acac5229261c2172e0e91` |
| Source size | 2.4 MiB |
| Основной лист | `Export Products Sheet` |
| Строк данных | 4,901 |
| Колонок | 87 |
| Формул | 0 |
| Reproduction | `cd backend && uv run python ../scripts/build_yuri_catalog_workbook.py SOURCE.xlsx OUTPUT.xlsx` |
| Machine metrics | `.artifacts/yuri_catalog/YURI_CATALOG_MARKO_INPUT_V1.metrics.json` |

Исходный XLSX не изменялся. Для работы создана отдельная копия;
после сохранения cell-value digests всех трёх исходных листов совпали.

## 3. Методика

Для каждой row-level proportion рассчитан 95% Wilson interval:

\[
\hat p=\frac{x}{n},\qquad
CI_{Wilson}=\frac{\hat p+\frac{z^2}{2n}\pm z
\sqrt{\frac{\hat p(1-\hat p)}{n}+\frac{z^2}{4n^2}}}
{1+\frac{z^2}{n}},\quad z=1.9599639845.
\]

OE normalization и fail-closed collision policy используют тот же code path, что и production import:
`backend/src/marko/services/xlsx_catalog.py`.

## 4. Измеренные результаты

| Метрика | Числитель / N | Point estimate | 95% Wilson CI | Вывод |
|---|---:|---:|---:|---|
| Товарные строки | 4,901 / 4,901 | 100.00% | — | Заявленное N подтверждено |
| Brand = `KEMP` / `КЕМР` | 4,620 / 4,901 | 94.27% | [93.58%, 94.88%] | Заявленные ~94% подтверждены |
| Синтаксически валидный OE | 4,900 / 4,901 | 99.98% | [99.88%, 100.00%] | Одна строка невалидна |
| Distinct normalized OE / rows | 4,774 / 4,901 | 97.41% | [96.93%, 97.82%] | Заявленные ~97% воспроизведены |
| Fail-closed auto-admissible OE rows | 4,647 / 4,901 | 94.82% | [94.16%, 95.40%] | Остальные 254 строки требуют review |
| Все 4 габарита | 1,083 / 4,901 | 22.10% | [20.96%, 23.28%] | Заявленные ~22% подтверждены |
| Currency = `UAH` | 4,901 / 4,901 | 100.00% | [99.92%, 100.00%] | Других валют нет |
| Product URL | 4,901 / 4,901 | 100.00% | [99.92%, 100.00%] | Missing URL = 0 |
| Prom.ua availability marker = available | 4,898 / 4,901 | 99.94% | [99.82%, 99.98%] | 3 позиции отмечены недоступными |
| Указан положительный остаток | 4,895 / 4,901 | 99.88% | [99.73%, 99.94%] | 3 zero-qty + 3 available rows без quantity |
| Manual `stock_status` | 0 / 4,901 | 0.00% | [0.00%, 0.08%] | Заполняет Юрий |
| Manual `stock_age_days` | 0 / 4,901 | 0.00% | [0.00%, 0.08%] | Необязательно; zero не выдумывается |

### 4.1. Collision inventory

| Показатель | Значение |
|---|---:|
| Duplicate raw OE groups | 119 |
| Rows inside duplicate raw OE groups | 239 |
| Normalized OE collision groups | 126 |
| Rows inside normalized collision groups | 253 |
| Syntactically invalid OE rows | 1 |
| Stable SKU duplicates (`Унікальний_ідентифікатор`) | 0 |
| Total manual-review rows | 254 |

Таким образом, 97.41% — это плотность различных normalized OE относительно числа
строк. Это **не** означает 97.41% automatic safe import. После исключения всех строк из
collision groups безопасный auto-admission равен 94.82%.

## 5. Рабочий XLSX

Создан `.artifacts/yuri_catalog/YURI_CATALOG_MARKO_INPUT_V1.xlsx`.

| Свойство | Результат |
|---|---|
| Output SHA-256 | `c0337041455cf36ff2a0919e8b8f87158368b82603badcd740072f4b83850af5` |
| Output size | 3,715,273 bytes |
| Формулы | 0 |
| Formula errors | 0 |
| Исходные листы | Сохранены, cell-value digests совпадают |
| Active sheet | `Ввод Юрия` |
| Marko parser result | 4,647 imported; 254 manual-review/rejected |

Новые листы:

1. `Инструкция` — краткие правила и измеренные факты.
2. `Ввод Юрия` — 4,901 строка, filters, frozen identity columns, yellow editable cells и Excel validation.
3. `Проверить OE` — все 254 проблемные строки с причиной, normalized OE, URL и действием.

Ручные поля:

- `stock_status`: ходовой / залежалый / неликвид / неизвестно;
- `stock_age_days`;
- `cost` — optional, encrypted on ingestion only under `SERVER_SIDE_ENCRYPTED`;
- 30/60/90-day sales, days since last sale, historical/expected monthly sales;
- views, conversion, manual priority, operator comment.

## 6. Import and privacy behavior

`backend/src/marko/services/xlsx_catalog.py` теперь:

- auto-detects Yuri's canonical Prom.ua headers;
- maps `Унікальний_ідентифікатор` to collision-free SKU;
- maps `Код_товару` to OE;
- maps the real product URL, MPN, brand, description, stock and Prom availability markers;
- accepts the optional manual sales columns from the working sheet;
- never places raw cost in `raw_row`, `CatalogItem.cost`, response or error payload;
- rejects a filled cost column when encrypted mode/keyring is unavailable;
- when encrypted mode is active, writes one AES-256-GCM append-only cost record per accepted row.

Важно: server-side encryption защищает значение **после ingestion**. В самом XLSX
заполненная себестоимость остаётся plaintext; это явно указано на листе
`Инструкция`.

## 7. Вывод

R-15 больше не `BLOCKED_DATA`: реальный каталог получен, content-addressed и измерен.
Заявленные 4,901 / ~94% KEMP / ~97% normalized identities / ~22% dimensions
воспроизведены. Для безопасной ценовой обработки без manual OE review автоматически
допускаются 4,647 rows; 254 строки явно вынесены на проверку.

Следующий внешний gate — не каталог, а permission-safe pinned Prom market replay.

## 8. Verification

- `uv run ruff check . ../scripts/build_yuri_catalog_workbook.py`: PASS.
- `uv run pytest -q`: **593 passed in 8.48s**.
- `dart format --output=none --set-exit-if-changed lib test`: 42 files, 0 changed.
- `dart analyze --fatal-infos`: no issues.
- `flutter test`: **25 passed**.
- `flutter build web --release`: PASS, `build/web` created.
- XLSX ZIP integrity: PASS, no compressed-data errors.
- Marko parse of original Prom sheet: 4,901 total; 4,647 imported; 254 review/rejected.
- Marko parse of generated active sheet: identical 4,901 / 4,647 / 254 partition.
- Generated workbook formula count: 0; formula-error count: 0.
