# Источники данных заказчика

Полный состав локальных входных данных проекта: каталог с ценами,
два справочника KEMP разных ревизий и номера, снятые с сайта заказчика.
Внешние Avto.pro/Exist.ua в эту таблицу не входят: они не являются локальными
файлами и не получают автоматического доверия.

Файлы в git с 2026-08-07: репозиторий приватный, и таблицу `sha256` ниже можно
сверить только тогда, когда закреплённые ею файлы лежат в том же коммите.
До этого числа они хранились локально, и таблица проверялась на слово.

Это данные заказчика: цены, описания, оптовые цены по артикулам. Приватность
репозитория — единственное, что их закрывает; в публичный репозиторий эти
файлы попадать не должны, а история git необратима без её перезаписи.

| Файл | sha256 (16) | Записей | Что это |
|---|---|---:|---|
| `kemp_prom_catalog.xlsx` | `7871f6b20b21d96b` | 4901 | Экспорт Prom: каталог с ценами и категориями |
| `kemp_oe_map.xls` → `.csv` | `fb37b2102c58b5a6` → `cb2b3c667f9efd8f` | 7743 | Справочник KEMP, ревизия 2026-07-29 (с колонкой «Номер») |
| `kemp_reference_map.xls` → `.csv` | `1fb10a10794421e8` → `54687209e28a4fc3` | 4646 | Справочник KEMP, ревизия 2026-07-28 (с колонкой «фирма по артикулу») |
| `kemp_site_numbers.csv` | `161bc16775c26f77` | 3224 | Номера, названия и primary-image provenance с карточек https://kemp.ua |

## Собственные витрины Prom и сайт KEMP

Это четыре витрины одного заказчика, а не независимые конкуренты. Их
объявления используются для подтверждения принадлежности, объединения
дубликатов и seed-side semantic evidence; их цены и продавцы исключаются из
конкурентной выборки до seller cap и до pricing.

| seller ID | витрина | canonical URL | роль |
|---:|---|---|---|
| `2847093` | KEMP | https://prom.ua/ua/c2847093-kemp.html | owned / seed |
| `4015921` | АвтоБуст | https://prom.ua/c4015921-avtobust.html | owned / duplicate evidence |
| `3325174` | PROFParts | https://prom.ua/ua/c3325174-profparts.html | owned / duplicate evidence |
| `3912822` | Parts Avto | https://prom.ua/ua/c3912822-parts-avto.html | owned / duplicate evidence |

Проверка не смешивает роли: `kemp.ua` — customer-owned product-card source,
Prom storefronts — customer-owned listing network, а public Prom offers вне
этих ID — market candidates. В текущем source contract все четыре ID уже
обязательны в `catalog_number_nature.yaml` и `comparability.yaml`; регрессии
`tests/test_owned_sellers_before_cap.py` доказывают исключение до ограничения
числа продавцов.

Повторно полученный Telegram-файл
`2_5424827205639252305 (2).xls` имеет другой raw OLE2 SHA-256
`819f54b0dc68e03e…`, но после read-only декодирования даёт тот же
мультинабор из 7743 строк, что и канонический
`2_5424827205639252305 (3).xls` (`fb37b2102c58b5a6…`). Это две
контейнерные копии одной логической ревизии, а не два
независимых источника и не два голоса в identity resolution.

### Coverage ceiling 2026-08-07 (no more customer data)

Локальный seed **исчерпан**: XLSX + 2 maps + harvest kemp.ua + discovery
multi-query tiers. Полный опрос 1974 `MPN_ONLY`/`UNRESOLVED` на kemp.ua
**не** открыл auto-OE (`KEMP_SITE` = REVIEW only). Файловый plan:
`OE_CONFIRMED` 5219 / `MPN_ONLY` 1954 / `UNRESOLVED` 20 (reference_codes
scope). Runtime catalog batch: ~2839 / ~1788 / 36.

Avto.pro (каталог KEMP) → **HTTP 403**. Обход 403 не делаем. Ждём ответа
владельца: это их прайс (export CSV/API) или чужая выкладка. Даже при
доступе Avto.pro/Exist = Tier C: не automatic `source_confirmed` /
`OE_CONFIRMED` без export-as-customer-data или HITL.

Пока ждём: multi-query на Prom уже в production path
(`fallback_queries` = confirmed CROSS, `discovery_queries` = public
MPN/parts; pricing primary остаётся OE). Снимок метрик:
`.artifacts/coverage_ceiling_baseline_20260807.json`.

### Telegram re-drop 2026-08-06

Заказчик повторно передал три файла и те же витрины. Побайтово:

| Telegram path | = `backend/data/…` | sha256 (16) |
|---|---|---|
| `2_5370668612929495405.xlsx` | `kemp_prom_catalog.xlsx` | `7871f6b20b21d96b` |
| `2_5422575405825567226 (6).xls` | `kemp_reference_map.xls` | `1fb10a10794421e8` |
| `2_5424827205639252305 (3).xls` | `kemp_oe_map.xls` | `fb37b2102c58b5a6` |

URL-ы `c2847093`, `c4015921`, `c3325174`, `c3912822` и `https://kemp.ua` —
уже каноническая owned-сеть (см. таблицу выше). Повторный импорт XLSX и
перезаливка maps **не нужны**: это та же ревизия, против которой уже
считались identity reparse и XLS-cross shadow. Новый рычаг покрытия —
`public_search_keys` (мульти-ключ из confirmed OE + one-hop + public MPN),
а не новые файлы.

## Приоритет и роли источников

Уточнение заказчика от 2026-08-05: оба переданных XLS нужно учитывать; если
их недостаточно, кроссы можно искать через Avto.pro или Exist.ua. Это задаёт
следующую границу:

1. `KEMP_REFERENCE_MAP_V2` — более свежая ревизия локального справочника;
2. `KEMP_REFERENCE_MAP_V1` — историческая ревизия того же publisher, поэтому не считается
   вторым независимым голосом;
3. `KEMP_REFERENCE_ARTICLE` — артикульные cross-кандидаты из тех же файлов, но не
   утверждение, что каждый артикул — OE;
4. Avto.pro/Exist.ua — только внешнее расширение после локальных файлов.

Находка из Avto.pro/Exist.ua не становится `CONFIRMED` только из-за имени сайта. Для
влияния на pricing scope нужны persisted claim/document, актуальная политика доступа,
прямая привязка обоих номеров и source/human confirmation. Avto.pro и Exist.ua не
считаются двумя независимыми голосами, пока не доказан разный upstream. Даже два
разных Tier C correlation group не могут дать `source_confirmed`:
автоматическое подтверждение требует один Tier A либо два независимых
Tier B source group. Tier C переходит в pricing scope только через положительный
persisted human review и hash-bound evidence snapshot.

## Происхождение

**`kemp_prom_catalog.xlsx`** — экспорт Prom.ua, три листа. Импортировать нужно
`Export Products Sheet` (4901 строка); `Лист1` содержит 16 строк с теми же
заголовками, и `_default_sheet()` отказывается выбирать между ними сам. Лист
указывается явно, иначе импорт молча даст 16 позиций вместо 4901.

Загружен в БД 2026-07-29: батч `374c07de-c00a-4ad9-ae17-2c4a2d39b070`,
4647 позиций из 4901. Отклонено 254: 253 — `NORMALIZED_OE_COLLISION` (две
разные записи дают один нормализованный ключ, нужен ручной разбор), 1 — пустой
OE в строке 203.

**`kemp_oe_map.xls` / `kemp_reference_map.xls`** — легаси OLE2/BIFF, `openpyxl`
их не читает. Конвертируются в CSV скриптом
`scripts/convert_kemp_reference_map.py`, который просит `xlrd` по требованию и
не тянет его в зависимости проекта. Раскладки колонок у двух ревизий
несовместимы и распознаются по имени заголовка, а не по порядку колонок.

**`kemp_site_numbers.csv`** — собран `scripts/kemp_site_harvest.py` по
конфигу `backend/config/kemp_site_tokens.yaml`. Манифест рядом:
`kemp_site_numbers.manifest.json`.

Ревизия 2026-08-07 расширила население с эвристики по бренду артикула на
факт: опрошены все 1974 кода, которые реперс идентичности всё ещё считает
`MPN_ONLY`/`UNRESOLVED`, плюс все 1115 опрошенных ранее (их строки сохранены
целиком — выкинуть код значило бы убрать его улику). 2101 код, 0 ошибок,
0 неразобранных карточек; 832 кода дали кандидата против 539 прежде.

Что этот файл **не** делает: ни одного статуса идентичности он не меняет.
`KEMP_SITE` объявлен `REVIEW` в `config/identity_graph.yaml:21-23`, потому что
подписи полей на карточке недостоверны, поэтому номер, который поставляет
только сайт, не становится подтверждённым OE сам собой. Проверено файловым
расчётом: `OE_CONFIRMED` 5219 и `MPN_ONLY` 1954 — одинаково с файлом и без
него. Продукт файла — материал для ревью: 425 связей с участием карточки
против 207 прежде.

Манифест хранит `reference_map_sha256s` — по одному sha на файл. Прежний
единственный ключ `reference_map_sha256` описывал одно издание; харвест теперь
читает оба, и склейка под старым именем выглядела бы как известная ревизия
справочника, не совпадая ни с одной.

## Кто читает

```
kemp_prom_catalog.xlsx   → marko.services.xlsx_catalog.import_catalog_xlsx
                           (POST /api/v1/catalog/imports)
kemp_oe_map.csv          → marko.services.catalog_identity_reparse
kemp_reference_map.csv   → marko.services.catalog_identity_reparse
kemp_site_numbers.csv    → metis.pricing.kemp_site
config/article_brand_kinds.yaml → load_article_brand_kinds
config/kemp_site_tokens.yaml    → load_kemp_site_tokens
```

## Что сходится и что нет

Сверено 2026-07-29:

- `kemp_site_numbers.manifest.json` → `reference_map_sha256s`
  `kemp_reference_map.csv` `54687209e28a4fc3…` и `kemp_oe_map.csv`
  `cb2b3c667f9efd8f…`, `method_version` `kemp-site-tokens-v2-card-evidence`,
  `requests_made=0` при повторном прогоне из кеша
  **совпадают** с обоими справочниками. Провенанс харвеста цел: видно,
  против каких ревизий справочника он считался.
- Structured-card replay 2026-08-06: dataset SHA `7996acb83c2cfec5…`,
  `requests_made=0`; JSON-LD binding fields are retained in the local ignored
  dataset and are checked fail-closed by the loader. Эта ревизия заменена
  2026-08-07 и лежит целиком в `backups/kemp_site_numbers_20260806/`; новая
  содержит её как подмножество (сверено мультимножеством строк).
  Строка `8d291557a4b521e5…`, стоявшая в таблице выше до 2026-08-07,
  не соответствовала ни одному файлу на диске: она осталась от ревизии,
  предшествовавшей structured-card replay. Актуальное значение —
  `161bc16775c26f77…`.
- `config/catalog_number_nature.yaml` → `source_catalog_sha256`
  `c0337041455cf36f…` **не совпадает** ни с одним файлом в проекте. Конфиг
  калибровался против снимка каталога от 2026-07-19
  (`catalog_id: yuri-prom-catalog-4901-2026-07-19`), которого здесь нет.
  Правила в нём — шаблоны номеров (`^776[0-9]{2,8}$` и подобные), а не
  привязка к строкам, поэтому они применимы и к текущему каталогу; но
  записанный хеш больше не проверяем. Обновлять его следует одновременно с
  перепроверкой правил, а не задним числом.

## Измеренные пересечения

Справочник 2026-07-29 против загруженного каталога (4647 позиций):

```
«Номер»             = catalog_items.oe_norm   4602  (99.0%)
«Номер производителя» = catalog_items.oe_norm    550
«Артикул»           = catalog_items.oe_norm    259
«Артикул»           = catalog_items.sku          0
```

Тот же справочник против витрин `listings` (49 100 товаров, синхронизированы
с Prom): совпало 307 артикулов из 4513, это 1204 листинга, 1190 из них — в
собственном магазине.

Покрытие сайтом: харвест дал 1385 позиций при каталоге на 4901, то есть
номера с карточек есть примерно для 28% каталога.

## Runtime status (2026-08-06)

Writer WP-6 реализован: `catalog-identity-reparse plan` строит полный план без
БД, а `apply` idempotent-но записывает связи и помечает устаревшие рёбра. После
проверенного backup локальная БД обновлена до `20260805_0048`, а runtime reparse
запущен для batch `374c07de-c00a-4ad9-ae17-2c4a2d39b070`: 2829 из 4647
импортированных клиентских позиций получили `OE_CONFIRMED`, 1782 остались
`MPN_ONLY`, 36 — `UNRESOLVED`. Это развёрнутый identity-контур, но не доказательство
рыночной ценовой точности: Prom-наблюдения по-прежнему требуют нового live shadow
прогона и ручной разметки.

Нормализационная коллизия OE теперь не удаляет исходные строки: все строки с
одним нормализованным OE сохраняются, но получают `UNRESOLVED` и причину
`NORMALIZED_OE_COLLISION`. Они видны оператору для ручного разбора и не могут
пройти identity/pricing admission автоматически. Это увеличивает полноту
импорта без ослабления safety-gate.

### OE-admission correction (2026-08-06)

Для `KEMP_SITE` второе подтверждение OE теперь считается только при наличии
двух независимых источников с `asserts_oe=true`. `KEMP_REFERENCE_ARTICLE`
подтверждает cross/артикул, но не превращает неразмеченный SKU сайта в OE.
Например для `77648791` связь `313452 -> 4853089025` сохраняется для поиска,
но каталог не получает `4853089025` как автоматически подтверждённый OE.
Карточные title/URL/image остаются в provenance и доступны оператору.

### Structured card binding (2026-08-06)

`kemp_site_harvest.py` дополнительно читает только неценовые поля
`schema.org/Product` JSON-LD: `name`, `brand`, `model`, `sku`, `mpn` и основное
изображение. Поля `offers.price`, `priceCurrency` и availability намеренно не
попадают в этот слой. Если JSON-LD присутствует, карточка принимается в
выборку только при точном нормализованном равенстве `Product.mpn` поисковому
внутреннему коду; `MPN_MISMATCH` вызывает fail-closed отказ. В сохранённом
кеше это дало 2 370 точных привязок из 2 372 строк CSV; 2 строки остались
`MISSING` и не получили более высокий уровень доверия. В manifest отдельно
записаны card-level counters (1 114 точных карточек, 1 154 `MPN_MISMATCH`,
3 `MISSING`) и row-level `record_counts`, чтобы разные знаменатели не
смешивались. Это повышает качество
привязки карточки, но не превращает один источник KEMP в автоматическое
подтверждение OE.

### Public source spot-check (2026-08-06)

Read-only verification of the four customer storefronts and the customer site
was performed after the local source reconciliation. The public Prom pages
identify АвтоБуст (`4015921`), ПРОФПАРТС (`3325174`) and Parts Avto (`3912822`)
as separate storefronts with large catalogues; their listings must remain
owned/duplicate evidence rather than independent competitors. The KEMP site
exposes structured identity fields on product cards: an OE number, an article,
a manufacturer and a KEMP manufacturer number are shown together on a sample
radiator card. These fields are useful for seed-side provenance and cross
discovery, but a site card is still one customer-owned source and does not
create a second independent confirmation by itself. Live prices are not
imported into the identity layer.

Контрольная карточка KEMP (read-only, 2026-08-06): [радіатор Audi-100
86–91](https://kemp.ua/kemp-radiator-audi-100-86-91-18-4cil-600307-ac-443121251t)
показывает `ОЕ номер=443121251T`, `Артикул=AI2091`, `Виробники=KEMP` и
`Номер виробника=77642803`. Это ровно тот тип раздельных полей, который нужен
для seed-side provenance; поле `offers.price` из JSON-LD в этот слой не
попадает. Контрольная карточка [заднего правого амортизатора Toyota Camry
V40](https://kemp.ua/kemp-amortizator-zadniy-praviy-toyota-camry-v40-2006-2011-313452)
показывает аналогичную связку `313452 / 4853089025 / KEMP / 77648791` и
сохраняет название и primary image для ручной проверки.

Публичная проверка также подтверждает, что [витрина KEMP на
Prom](https://kemp-cs2847093.prom.ua/ua/) публикует ту же Camry-позицию `313452`,
а [АвтоБуст](https://prom.ua/c4015921-avtobust.html) и [Parts
Avto](https://prom.ua/c3912822-parts-avto.html) являются отдельными витринами
владельца с большими каталогами. Это не независимые рыночные голоса: их
seller IDs остаются в owned-network quarantine. Ссылка на [витрину
ПРОФParts](https://prom.ua/ua/c3325174-profparts.html) сохранена в таблице
источников даже когда конкретный live fetch Prom временно недоступен.
