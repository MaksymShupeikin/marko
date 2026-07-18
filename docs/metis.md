# Metis — полное описание продукта, математическая модель, связь с кодом Marko, план доработки и деплоя

**Документ-назначение.** Этот файл сохраняет бизнес-модель **Metis** и исходный инженерный бриф для реализации в репозитории **Marko** (`marko — копия/`).  
**Аудитория.** Человек (продакт/разработчик) и ИИ-агент, который будет дописывать код.  
**Язык.** Русский + формальные определения, псевдокод и ссылки на файлы репозитория.  
**Правило приоритета.** Список «что можно добавить» **не** является текущим драйвером проекта. Драйвер — **замер покрытия рынка на Prom по чистому OE** (протокол §12). Без него нельзя честно продавать Слой 6 (частичные кроссы).

> **Статус реализации на 2026-07-16.** Исторические пометки `as-is`, проценты
> готовности и списки `To-build` ниже описывают состояние до текущей
> реализации. Сейчас в коде уже есть XLSX import, first-class OE, PricingRun,
> масштабирование вокруг неизменённого Prom parser, append-only market
> evidence/tiering, обе модели коэффициентов, robust fair price, confidence
> abstention, fresh/stale/dead_stock modes, priority, audit decisions и Flutter
> UI. Актуальные пути: `backend/src/metis/pricing/`,
> `backend/src/marko/services/{xlsx_catalog,market_collection,pricing_runs}.py`,
> migrations `20260716_0005` + `20260716_0006`, API `/catalog` + `/pricing`, Flutter features
> `catalog/` + `pricing/`. Старые gap-таблицы не следует использовать как
> текущий отчёт о готовности.

---

## 0. Глоссарий (термины, которые обязан понимать агент)

| Термин | Определение |
|---|---|
| **Metis** | Продукт: инструмент ценообразования для продавца автозапчастей на Prom.ua; один (или периодический) **прогон** каталога → таблица рекомендаций «поднять / слить / вручную» с приоритетом |
| **Marko** | Репозиторная реализация Metis: modular monolith (Flutter + FastAPI + Celery + PostgreSQL + Redis + Prom parser) |
| **Клиент / workspace** | Продавец (бренд **KEMP**, бюджетный аналог), ~**4901** SKU, товар физически на складе |
| **SKU / listing** | Конкретная позиция каталога клиента (строка экспорта / карточка Prom) |
| **OE / OEM-номер** | Оригинальный номер детали (например `1K0698151E`). Основной ключ поиска рынка в MVP |
| **Уровень (tier / quality level)** | Класс предложения: оригинал VAG, OES (Bosch/Nissens), аналог A (Febi/Meyle), бюджетный аналог (KEMP), б/у |
| **Приведённая цена** | Цена конкурента, нормализованная к уровню клиента коэффициентом \(k\) |
| **Справедливая цена \(P^\*\)** | Робастная медиана приведённых цен (после IQR-фильтра) |
| **Режим стока** | `fresh` (ходовой) / `slow` (лежалый) / `dead` (неликвид) — пометка клиента |
| **Себестоимость \(C\)** | По умолчанию вводится клиентом вручную внутри приложения; XLSX-колонка не автоопределяется (явный mapping возможен). Себестоимость — ограничение/контекст, а не вход в рыночную fair price |
| **Прогон (pricing run)** | Версионированный batch: catalog snapshot + market scrape + tiering + recommendations |
| **Слой 6 / кроссы** | Связь разных артикулов одной детали (OE ↔ Febi ↔ TRW). **Вне MVP.** Платное расширение только после замера |
| **Prom** | Единственная площадка MVP. Autopro — out of scope |
| **Sunk cost** | Историческая закупочная стоимость с учётом курса; **не** вход в \(P^\*\) |

---

## 1. Что такое Metis (одно предложение + развёртка)

**Metis** — это система, которая для каталога продавца автозапчастей на Prom.ua за один прогон:

1. берёт **его** текущие цены и OE-номера;
2. собирает **рынок** по тем же OE;
3. **не сравнивает в лоб** оригинал с бюджетным аналогом;
4. приводит чужие цены к **уровню клиента**;
5. считает **справедливую цену** робастной медианой;
6. выдаёт рекомендации **только в безопасном направлении** (вверх для ходового, вниз для залежалого);
7. фильтрует по **уверенности**;
8. **сортирует** по деньгам, а не по алфавиту;
9. даёт **ссылки** на конкурентов как инструмент доверия.

### 1.1. Для кого

| Параметр | Значение |
|---|---|
| Клиент | Продавец на Prom.ua |
| Каталог | ~4901 позиция |
| Бренд | KEMP (бюджетный аналог) |
| Склад | Физический (не dropship-абстракция) |
| Проблема | Не знает, где недозарабатывает; вручную проверить 4901 OE = месяцы; цены «стоят годами» |
| Цель одного прогона | «Вот здесь поднять, вот здесь сливать, вот в таком порядке» |

### 1.2. Что Metis **не** является

- Не маркетплейс-агрегатор для покупателя.
- Не «сравни с самой дешёвой ценой на Prom» (это ломает маржу на неверной уровневой логике).
- Не TecDoc / кросс-база уровня TecAlliance.
- Не автопилот публикации цен (MVP — рекомендации + ручное изменение).
- Не 1С/BAS-интеграция.
- Не Autopro (только Prom).

### 1.3. Зафиксированные запреты (product constraints)

| Запрет | Причина |
|---|---|
| Autopro | Out of scope MVP; другой парсер |
| Автопубликация цен | Опасно; клиент меняет руками |
| 1С/BAS | Отдельный платный контур |
| Сопоставление аналогов по **разным** артикулам (TecDoc-кроссы) | Платная лицензия, не влезает в бюджет ~€1500 |
| Автоматическое извлечение себестоимости | Себестоимость вводит клиент явно; каждое below-cost действие требует отдельного подтверждения и audit trail |

---

## 2. Проблема формально

### 2.1. Исходные данные

Пусть каталог клиента:

\[
\mathcal{C} = \{ i = 1..N \}, \quad N \approx 4901
\]

Для каждого SKU \(i\):

| Символ | Смысл | Источник |
|---|---|---|
| \(oe_i\) | OE-номер (нормализованный) | xlsx-экспорт Prom / listing |
| \(name_i\) | Название | экспорт / Prom |
| \(cat_i\) | Категория | экспорт / Prom category |
| \(P_i^{own}\) | Текущая цена клиента | экспорт / listing.current_price |
| \(s_i \in \{\text{fresh}, \text{slow}, \text{dead}\}\) | Режим стока | **клиент вручную** |
| \(C_i\) | Себестоимость | **только клиент**, client-side |
| \(f_i\) | Частота/вес продаж (прокси) | клиент / эвристика / константа 1 |

### 2.2. Наблюдаемый рынок

По запросу \(oe_i\) (и/или search) на Prom получаем множество предложений:

\[
\mathcal{M}_i = \{ j = 1..m_i \}
\]

где у \(j\):

- \(P_{ij}\) — цена,
- \(seller_{ij}\) — продавец,
- \(brand_{ij}\), \(name_{ij}\), \(avail_{ij}\), \(url_{ij}\),
- \(raw_{ij}\), \(t_{obs}\) — сырой снимок + timestamp.

### 2.3. Почему «сравнить в лоб» ломает бизнес

Один и тот же OE `1K0698151E` (иллюстрация из продуктового брифа):

| Уровень | Пример бренда | Цена (иллюстрация) |
|---|---|---:|
| OEM / оригинал | VAG | 3200 |
| OES | Bosch, Nissens | 2000 |
| Аналог A | Febi, Meyle | 1400 |
| Бюджетный аналог (уровень клиента) | KEMP | 850 |
| б/у | — | 400 |

Разброс до ~4×. Если \(P^\* = \mathrm{median}(\{3200,2000,1400,850,400\})\) без уровней — система скажет «поднимай к 1400–2000+», клиент поднимет KEMP и **не продаст**.

**Инвариант продукта:** сравнение допустимо только после **приведения к уровню клиента** или после **исключения** несовместимых уровней.

### 2.4. Целевая функция прогона

Для каждого \(i\) вычислить:

\[
R_i = (a_i,\ P_i^\*,\ \Delta_i,\ conf_i,\ rank_i,\ links_i)
\]

где:

- \(a_i \in \{\text{raise}, \text{lower}, \text{hold}, \text{manual}\}\) — действие,
- \(P_i^\*\) — справедливая цена (если определена),
- \(\Delta_i\) — денежный эффект (недозаработок или «разморозка»),
- \(conf_i\) — уверенность / флаг manual,
- \(rank_i\) — порядок работы,
- \(links_i\) — URL конкурентов.

Сортировка UI:

\[
rank_i \propto |\Delta_i| \cdot w(f_i)
\]

а не алфавит `name_i`.

---

## 3. Архитектура продукта (логические слои Metis)

```text
┌─────────────────────────────────────────────────────────────────┐
│  L0  Identity / Workspace (Firebase → users/workspaces)         │
├─────────────────────────────────────────────────────────────────┤
│  L1  Catalog Ingest (xlsx Prom 87 cols +/or scrape own store)   │
├─────────────────────────────────────────────────────────────────┤
│  L2  Market Collect (search by OE → offers + raw + timestamp)   │
├─────────────────────────────────────────────────────────────────┤
│  L3  Tier Classification (OEM/OES/A/budget/used + filters)      │
├─────────────────────────────────────────────────────────────────┤
│  L4  Level Coefficients (k by category → global fallback)       │
├─────────────────────────────────────────────────────────────────┤
│  L5  Fair Price (IQR + robust median of adjusted prices)        │
├─────────────────────────────────────────────────────────────────┤
│  L6  Cross-refs from descriptions  [OPTIONAL, after measure]    │
├─────────────────────────────────────────────────────────────────┤
│  L7  Recommendation modes (fresh↑ / slow·dead↓) + confidence    │
├─────────────────────────────────────────────────────────────────┤
│  L8  Priority ranking (Δ × sales weight) + competitor links     │
├─────────────────────────────────────────────────────────────────┤
│  L9  UI: run status, table, manual review, client-side cost     │
└─────────────────────────────────────────────────────────────────┘
```

**Текущий статус:** L0–L5 и L7–L9 реализованы в Marko: immutable XLSX
snapshot, batch market collection вокруг неизменённого parser, append-only
tiering, paired-OE calibration, KEMP normalization, robust fair price,
confidence gates, stock modes, typed priority, recommendation API и Flutter UI.
L6 cross-references по разным артикулам остаётся отдельным scope после замера.

---

## 4. Связь Metis ↔ текущий код Marko (as-is)

### 4.1. Стек (deployable skeleton)

```text
Flutter (web/Android/desktop)
   │  Firebase ID token
   ▼
FastAPI  ──► PostgreSQL 17
   │
   └──► Redis ──► Celery worker / beat ──► prom.ua (HTTP + Apollo cache)
```

Ключевые пути:

| Компонент | Путь |
|---|---|
| Compose | `compose.yaml` |
| API entry | `backend/src/marko/api/main.py` |
| Config | `backend/src/marko/core/config.py` |
| ORM | `backend/src/marko/infrastructure/db/models.py` |
| Prom HTTP | `backend/src/marko/parsers/prom/client.py` |
| Apollo parse | `backend/src/marko/parsers/prom/parser.py` |
| Gateway scrape/compare | `backend/src/marko/parsers/prom/gateway.py` |
| Matching | `backend/src/marko/services/matching.py` |
| Catalog import task | `backend/src/marko/services/catalog_import.py` + `worker/tasks/import_store.py` |
| CLI | `backend/src/marko/cli.py` (`scrape`, `compare`) |
| Frontend | `frontend/lib/features/{auth,dashboard,stores}` |

### 4.2. Что уже есть (можно reuse)

| Capability | Где | Комментарий |
|---|---|---|
| Auth Firebase → local user/workspace | `services/auth.py`, migration `0004` | L0 готов концептуально |
| Регистрация store URL + async import | `api/routers/v1/stores.py`, Celery | L1 partial: scrape, не xlsx |
| Listings + price_observations append-only | models | История цен — задел phase2 |
| Product fields: sku, brand, model_id, category_id | `parser_models.Product` | База для OE/tier |
| Search multi-seller + match tiers model/sku/fuzzy | `gateway.compare`, `matching.match_offer` | L2/matching prototype |
| Token similarity + laterality antonyms | `matching.py` | Полезно, но **не** заменяет OE-level market |
| Median/min/max/spread stats | `PriceComparison` | **Не** IQR, **не** level-adjusted |
| Docker stack + health | compose, `/health/live|ready` | Локальный деплой есть |
| UI stores/products | Flutter | Нет pricing run / recommendations |

### 4.3. Критический gap: Marko matching ≠ Metis pricing

Текущий `match_offer` (упрощённо):

```text
IF model_id equal → score 1.0
ELIF sku equal → score 1.0
ELIF brands_compatible AND name_similarity ≥ threshold AND NOT laterality_conflict
     → fuzzy score
ELSE reject
```

`brands_compatible` **отклоняет** разные бренды, если оба известны:

```python
# matching.py
return not a or not b or a == b
```

Для Metis это **противоположно** нужному поведению на рынке одной детали:  
**нужны** VAG / Bosch / Febi / KEMP на **одном OE**, затем **переклассификация уровня**, а не отсев «чужого бренда».

`build_comparison` берёт **самую дешёвую** оферту продавца и считает `median(prices)` **без** tiering → прямой путь к ошибке «поднимись к OEM».

**Вывод для агента:** CLI `compare` — инструмент разведки и scrape QA.  
**Pricing engine Metis — новый модуль** (например `services/pricing/`), не «чуть подкрутить threshold».

### 4.4. Gap по данным

| Нужно Metis | Есть в Marko | Gap |
|---|---|---|
| Импорт xlsx 87 колонок Prom | Нет | Новый parser + mapping OE |
| OE как first-class field | `sku` / raw only | `oe_number` normalized + index |
| Tier labels | Нет | brand→tier dict + rules used |
| Category-level \(k\) | Нет | таблица коэффициентов / job |
| Stock mode fresh/slow/dead | Нет | client annotation entity |
| Cost client-only | Нет | Flutter local storage / encrypted field, **не** в API по умолчанию |
| PricingRun + Recommendation rows | Нет | новые таблицы |
| Batch market by OE for 4901 | Только single-URL compare | worker fan-out + rate limit |
| Confidence gate | spread_pct only | formal conf formula |
| Priority \(\Delta \times f\) | Нет | ranking service |
| Competitor links in UI | partial in CLI | API + Flutter table |

### 4.5. Оценка зрелости (честная)

| Слой | Готовность |
|---|---:|
| L0 Auth/workspace | ~70% (prod secrets/TLS ещё нет) |
| L1 Catalog | ~40% (scrape yes, xlsx no, OE quality unproven in code) |
| L2 Market collect | ~35% (single compare; no batch pipeline) |
| L3–L5 Pricing core | ~0–5% (median exists, logic wrong for auto parts levels) |
| L7–L8 Recommend + rank | ~0% |
| L9 Metis UI | ~15% (shell: stores/products) |
| Production deploy | ~25% (compose dev; no prod compose/TLS/observability) |

---

## 5. Пайплайн Metis — пошагово (как должен работать end-to-end)

Ниже — **целевая** спецификация. Где уместно, указано «as-is Marko» vs «to-build».

### Step 0. Создать Pricing Run

**Вход:** `workspace_id`, `store_id` (owned), параметры scrape (delay, max concurrency).  
**Выход:** `pricing_run_id`, status `queued`.

**Состояния:**

```text
queued → ingesting_catalog → collecting_market → computing_tiers
      → computing_fair_prices → recommending → completed | failed
```

**As-is:** есть `SyncRun` только для catalog import.  
**To-build:** `PricingRun` (или обобщить `SyncRun.kind` + payload JSON).

---

### Step 1. Забрать каталог

#### 1.A. Целевой путь Metis: xlsx-экспорт Prom (87 колонок)

1. Клиент выгружает каталог из Prom (xlsx).
2. Система парсит строки, маппит колонки:

| Логическое поле | Назначение |
|---|---|
| external_id / product_id | стабильный id |
| name | название |
| category | \(cat_i\) |
| price | \(P_i^{own}\) |
| OE / артикул / код | \(oe_i\) (критично) |
| brand | для self-tier = budget (KEMP) |
| url | deep link |

3. Нормализация OE:

```text
function normalize_oe(raw):
  s = upper(strip(raw))
  s = remove spaces, dashes, underscores (policy: keep alnum only OR keep OEM punctuation consistently)
  return s if len(s) >= MIN_OE_LEN else NULL
```

4. Метрика качества:

\[
q_{oem} = \frac{|\{i: oe_i \neq \emptyset\}|}{N}
\]

По брифу клиента: \(q_{oem} \approx 0.97\) — **редкость и преимущество**.  
Если \(q_{oem} < 0.90\) — прогон должен предупредить: покрытие рынка искусственно узкое.

#### 1.B. As-is Marko: scrape own store

`PromGateway.scrape(canonical_url)` → `Listing` + `PriceObservation`.  
Поля: `sku`, `brand`, `model_id`, `category_id` из Apollo.  
**Не гарантирует** OE-качество 97% — зависит от того, что продавец кладёт в `sku`/название.

**Рекомендация реализации:**  
- MVP-run: **xlsx primary** (контракт с клиентом).  
- scrape store — secondary sync / refresh prices & availability.  
- оба пишут в одну модель listing + source tag.

#### 1.C. Persist

Для каждого \(i\): upsert listing, snapshot run-item:

```text
pricing_run_items(
  run_id, listing_id, oe_normalized, name, category, own_price, stock_mode, ...
)
```

---

### Step 2. Собрать рынок (по каждому OE)

#### 2.1. Поиск

Для каждого \(oe_i \neq \emptyset\):

```text
query = oe_i   # primary
# optional fallback: oe_i + short name tokens (careful: noise)
candidates = Prom.search(query, pages=1..K)
```

**As-is:** `PromGateway._collect_candidates` + `parse_search` (SearchListingQuery).  
Default `max_search_pages=3`, delay ~1s + jitter.

#### 2.2. Сохранение observation

Для каждого кандидата \(j\):

```text
save competitor_offer:
  run_id, source_item_id, seller_id, seller_name,
  price, currency, availability, brand, name, url,
  match_basis = "oe_search" | "model_id" | ...,
  raw_json, observed_at
```

**Инвариант:** raw + timestamp обязательны (аудит, доверие, debug tiering).

#### 2.3. Масштаб и rate-limit (инженерно критично)

Грубая оценка wall-time:

\[
T_{market} \approx N \cdot K \cdot (d + \varepsilon)
\]

где \(d \approx 1.0\) s base delay, \(K\) страниц поиска, \(N=4901\).

При \(K=2\), \(d=1.2\), последовательно:

\[
T \approx 4901 \cdot 2 \cdot 1.2 \approx 11762\ \text{s} \approx 3.3\ \text{h}
\]

Плюс product pages / retries / empty pages.  
**Вывод:** batch market collect — **Celery chord/group**, concurrency ограниченная (например 2–4), polite delay, checkpoint progress в `pricing_run`, идемпотентность по `(run_id, oe)`.

**Не делать:** синхронный HTTP из FastAPI request.

#### 2.4. Дедуп

- per seller keep best available offer (policy: min price among available; if all unavailable — mark separately).  
- exclude own `seller_id` / own store.  
- exclude other KEMP sellers **на этапе L3**, не на HTTP (нужен brand/tier).

---

### Step 3. Определить уровень каждого конкурента (ядро)

#### 3.1. Дискретное множество уровней

\[
L = \{\ell_{used},\ \ell_{budget},\ \ell_{analogA},\ \ell_{oes},\ \ell_{oem}\}
\]

Уровень клиента (KEMP): \(\ell_{self} = \ell_{budget}\).

#### 3.2. Классификатор \(\tau(j) \rightarrow \ell \cup \{\text{unknown}\}\)

Правила (приоритет сверху вниз):

1. **Used filter**  
   Если в `name`/`description` есть маркеры б/у:  
   `б/у`, `бу`, `used`, `восстанов`, `реставр`, `разбор`, `second hand` → \(\ell_{used}\).  
   **Действие:** **выбросить** из \(\mathcal{M}_i^{usable}\).

2. **Same-brand dump filter**  
   Если brand ∈ {KEMP, … aliases} **и** seller ≠ self → **выбросить**  
   (демпинг того же товара другими).

3. **Brand dictionary**  
   - OEM brands / «оригинал» + VAG/OEM markers → \(\ell_{oem}\)  
   - Bosch, Nissens, … → \(\ell_{oes}\)  
   - Febi, Meyle, … → \(\ell_{analogA}\)  
   - KEMP, и др. budget → \(\ell_{budget}\)

4. **Price-relative weak prior** (только если brand unknown; **не** как единственный сигнал)  
   Относительно медианы уже размеченных в той же категории — soft score, иначе `unknown`.

5. **Unknown policy**  
   - либо exclude,  
   - либо include only if conf later high;  
   default MVP: **exclude from \(P^\*\)**, но показать в links as «не классифицировано».

#### 3.3. Почему бренд-словарь обязателен

Без \(\tau\): residual mixture prices → раздутый IQR → `manual` почти всегда **или** ложный raise к OEM.  
Словарь — versioned artifact: `tier_dictionary_v{semver}.json` + `matcher_version` в результатах.

#### 3.4. Пример (тот же OE)

| j | brand | raw price | tier | keep? |
|---|---|---:|---|---|
| 1 | VAG | 3200 | oem | yes |
| 2 | Bosch | 2000 | oes | yes |
| 3 | Febi | 1400 | analogA | yes |
| 4 | KEMP (other) | 800 | budget | **drop (same brand dump)** |
| 5 | б/у | 400 | used | **drop** |
| 6 | KEMP (self) | 850 | — | drop (own) |

---

### Step 4. Коэффициенты уровня (category → global fallback)

#### 4.1. Идея

Оригинал «примерно вдвое дороже» аналога **не** константа 2.0 глобально.  
Оцениваем отношение уровней **на сотнях SKU внутри категории**.

Определим референс-уровень \(\ell_{ref} = \ell_{budget}\) (уровень клиента).

Для каждого уровня \(\ell\) и категории \(c\):

Собрать пары на пересечении OE (или run items), где есть и \(\ell\), и \(\ell_{ref}\):

\[
r_{c,\ell}^{(u)} = \frac{P^{(u)}_{\ell}}{P^{(u)}_{ref}}
\]

по единицам \(u\) (SKU/OE) внутри категории \(c\).

#### 4.2. Оценка коэффициента

\[
\hat{k}_{c,\ell} = \mathrm{median}_u \left( r_{c,\ell}^{(u)} \right)
\]

при условии:

\[
n_{c,\ell} = |\{u\}| \ge n_{min}^{cat}
\]

Рекомендуемые defaults (калибруемые):

- \(n_{min}^{cat} = 30\) (порядок «десятки–сотни»; ниже — fallback),
- если \(n_{c,\ell} < n_{min}^{cat}\): \(\hat{k}_{c,\ell} = \hat{k}_{global,\ell}\),
- если global тоже мал: hard prior \(k^{prior}\) (например oem≈2.0, oes≈1.5, analogA≈1.2 — **как bootstrap**, не dogma).

#### 4.3. Приведение цены конкурента к уровню клиента

\[
\tilde{P}_{ij} = \frac{P_{ij}}{\hat{k}_{c_i,\ \tau(j)}}
\]

Интерпретация: «сколько **стоил бы** этот товар, если бы был уровня KEMP».

Пример: OEM 3200, \(\hat{k}_{oem}=2.0\) → \(\tilde{P}=1600\).  
OES 2000, \(k=1.6\) → 1250.  
AnalogA 1400, \(k=1.25\) → 1120.

#### 4.4. Почему не по одной позиции

На одном OE часто 2–4 точки. Оценка \(k\) по 3 точкам — **шум**.  
Категория даёт \(n \gg 1\). Это ключевой статистический принцип продукта.

#### 4.5. Запрет обратной связи (implementation note)

Коэффициенты для run \(R\) считать либо:

- по **предыдущему** completed run, либо  
- two-pass: pass1 estimate \(k\) on raw tier medians across catalog, pass2 adjust,

но **не** так, чтобы \(P^\*\) и \(k\) бесконечно подгоняли друг друга в одном SKU.

---

### Step 5. Справедливая цена \(P^\*\) (робастная медиана)

#### 5.1. Множество приведённых цен

\[
\mathcal{A}_i = \{ \tilde{P}_{ij}\ :\ j \in \mathcal{M}_i^{usable},\ \tilde{P}_{ij} > 0 \}
\]

#### 5.2. IQR outlier drop

Пусть \(Q1, Q3\) — квартили \(\mathcal{A}_i\), \(IQR = Q3 - Q1\).

\[
\mathcal{A}_i^{rob} = \{ x \in \mathcal{A}_i\ :\ Q1 - \alpha\cdot IQR \le x \le Q3 + \alpha\cdot IQR \}
\]

Default \(\alpha = 1.5\) (Tukey).  
Если после фильтра \(|\mathcal{A}_i^{rob}| < n_{min}^{price}\): fallback к \(\mathcal{A}_i\) **или** `manual` (см. conf).

#### 5.3. Медиана, не среднее

\[
P_i^\* = \mathrm{median}(\mathcal{A}_i^{rob})
\]

**Почему не mean:** на 4 точках, из которых 1–2 мусор (неверный tier/match), mean смещается; median устойчивее.

#### 5.4. Доп. статистики (для UI/debug)

\[
\begin{aligned}
spread_i &= \frac{\max \mathcal{A}_i^{rob} - \min \mathcal{A}_i^{rob}}{P_i^\*} \\
cv_i &= \frac{\mathrm{std}(\mathcal{A}_i^{rob})}{P_i^\*} \quad (\text{optional})
\end{aligned}
\]

As-is Marko `spread_pct = (max-min)/min*100` — **другая** нормализация; для Metis лучше relative to \(P^\*\) или robust IQR/median.

---

### Step 6. Режим рекомендации (два режима + hold/manual)

#### 6.1. Режим `fresh` (ходовой) — **только вверх**

\[
a_i =
\begin{cases}
\text{raise} & \text{if } conf_i \ge \theta\ \wedge\ P_i^\* > P_i^{own}(1+\varepsilon_{up}) \\
\text{hold} & \text{if } conf_i \ge \theta\ \wedge\ P_i^\* \le P_i^{own}(1+\varepsilon_{up}) \\
\text{manual} & \text{if } conf_i < \theta
\end{cases}
\]

- \(\varepsilon_{up}\) — минимальный относительный зазор (например 0.03 = 3%), чтобы не шуметь из-за копеек.  
- **Никогда** не советовать `lower` в `fresh`.  
  **Инвариант безопасности:** система не уводит ходовой товар в минус «потому что рынок ниже» (клиент мог иметь особые условия/остатки/акцию).

Рекомендуемая цена при raise:

\[
P_i^{rec} = P_i^\* \quad \text{(или conservative: } \min(P_i^\*,\ P_i^{own}\cdot(1+\delta_{max}))\text{)}
\]

#### 6.2. Режим `slow` / `dead` (лежалый / неликвид) — **вниз**

Цель: слить, высвободить деньги.

\[
a_i =
\begin{cases}
\text{lower} & \text{if } conf_i \ge \theta\ \wedge\ P_i^{rec} < P_i^{own}(1-\varepsilon_{down}) \\
\text{hold} & \text{if market not below enough} \\
\text{manual} & \text{if low conf}
\end{cases}
\]

Политика \(P^{rec}\) для slow/dead (пример):

- `slow`: \(P^{rec} = \max(P^\* \cdot \beta_{slow},\ \text{client floor if any})\)  
- `dead`: \(P^{rec} = P^\* \cdot \beta_{dead}\) with \(\beta_{dead} \le \beta_{slow} < 1\) (агрессивнее)

#### 6.3. Себестоимость \(C_i\) — client-side only

- Сервер **не требует** \(C_i\).  
- UI локально может подсветить:  
  - `fresh/slow`: warn if \(P^{rec} < C_i\);  
  - `dead`: allow \(P^{rec} < C_i\) **явно** (решение клиента), но показать «ниже себестоимости».

**Не смешивать** \(C_i\) с \(P^\*\). \(P^\*\) — market-level construct; \(C\) — private constraint.

#### 6.4. Sunk cost / курс НБУ (phase2 only)

Клиент вводит дату/валюту закупки → система тянет курс НБУ на дату → показывает «сколько потеряно с учётом времени».  
**Справка, не вход в \(P^{rec}\)**. Иначе клиент будет задирать неликвид «чтобы отбить».

---

### Step 7. Уверенность \(conf_i\) и self-diagnostics

#### 7.1. Факторы

1. **Размер выборки** \(n_i = |\mathcal{A}_i^{rob}|\)  
2. **Разброс** \(spread_i\) (или \(IQR/P^\*\))  
3. **Доля unknown/dropped** (качество tiering)  
4. **Match basis quality** (oe exact ≫ fuzzy name)

#### 7.2. Предлагаемая формула (калибруемая)

\[
conf_i = \underbrace{\phi_n(n_i)}_{\text{sample}} \cdot \underbrace{\phi_s(spread_i)}_{\text{dispersion}} \cdot \underbrace{\phi_q(q_i)}_{\text{tier quality}}
\]

Пример кусочных \(\phi\):

\[
\phi_n(n) =
\begin{cases}
0 & n < 2 \\
0.4 & n = 2 \\
0.7 & n \in [3,4] \\
1.0 & n \ge 5
\end{cases}
\qquad
\phi_s(s) =
\begin{cases}
1.0 & s \le 0.25 \\
0.6 & s \in (0.25, 0.50] \\
0.2 & s \in (0.50, 0.80] \\
0 & s > 0.80
\end{cases}
\]

\[
q_i = 1 - \frac{n_{unknown}+n_{conflict}}{n_{raw}+1}
\]

Порог \(\theta\) default: **0.55–0.65** (выбрать после замера).

#### 7.3. Self-diagnostics

Большой \(spread_i\) при \(n_i\) умеренном **часто** = смесь уровней (ошибка \(\tau\)).  
UI: «проверьте вручную» + показать raw offers по уровням.  
Это не «просто нет рекомендации» — это **сигнал качества классификатора**.

#### 7.4. Gate

\[
\text{if } conf_i < \theta:\ a_i = \text{manual},\ P^{rec}=\text{null},\ \text{reason code}
\]

Reason codes (enum): `LOW_N`, `HIGH_SPREAD`, `NO_OE`, `NO_MARKET`, `TIER_MIX`, `ALL_DROPPED`.

---

### Step 8. Приоритет (порядок работы)

#### 8.1. Денежный эффект

**Raise (fresh):**

\[
\Delta_i^{up} = \max(0,\ P_i^{rec} - P_i^{own})
\]

**Lower (slow/dead):** «разморозка» / скорость слива — proxy:

\[
\Delta_i^{down} = \max(0,\ P_i^{own} - P_i^{rec}) \cdot \lambda(s_i)
\]

где \(\lambda(dead) > \lambda(slow)\) (неликвид важнее высвободить).

#### 8.2. Вес продаж

\(f_i\) — частота продаж (клиент / CSV / эвристика).  
Если нет данных: \(f_i = 1\) или segment weights.

\[
Score_i = \Delta_i \cdot w(f_i)
\]

Сортировка: `Score` desc, затем `conf` desc, затем name.

**Инвариант UX:** не алфавит первой строкой.

---

### Step 9. Ссылки на конкурентов (trust layer)

Для каждой строки рекомендации:

- top offers used in \(P^\*\) with url, price, brand, tier, adjusted price;
- optionally excluded offers with reason (`used`, `same_brand`, `outlier`).

Клиент кликает → видит тот же товар на Prom → верит цифре.  
**Без links Metis не продаётся** как инструмент доверия.

---

## 6. Математическая сводка (один блок для реализации)

```text
INPUT:
  catalog C, stock modes s_i, client level ℓ_self=budget
  optional: sales weights f_i
  NOT REQUIRED: cost C_i (client-side only)

FOR each category c:
  estimate k̂_{c,ℓ} from multi-SKU tier price ratios
  fallback to k̂_global,ℓ then k_prior

FOR each SKU i with oe_i:
  M_i ← market_offers(oe_i)
  drop used, drop other same-brand budget dumpers, drop own
  for j in M_i: tier ← τ(j);  P̃_ij ← P_ij / k̂_{c_i, tier}
  A ← {P̃_ij}
  A_rob ← IQR_filter(A, α=1.5)
  P*_i ← median(A_rob)
  conf_i ← Φ(n, spread, tier_quality)
  IF conf < θ: action=manual
  ELSE IF s_i == fresh:
      action = raise if P* > P_own*(1+ε) else hold
      never lower
  ELSE: # slow/dead
      action = lower toward discounted P* if below own
  Δ_i ← money impact
  Score_i ← Δ_i * w(f_i)
  links_i ← competitor URLs

OUTPUT:
  table sorted by Score_i desc
```

---

## 7. Что Metis НЕ делает (зафиксировано) + главное ограничение

### 7.1. Out of scope MVP

| Функция | Статус |
|---|---|
| Autopro | нет |
| Автопубликация цен | нет |
| 1С/BAS | нет |
| TecDoc / полные кроссы артикулов | нет |

### 7.2. Главное ограничение: разные артикулы одной детали

Пример:

| Источник | Номер |
|---|---|
| OE клиента | `1K0698151E` |
| Febi | `16510` |
| TRW | `GDB1550` |

Поиск по **точному OE** не видит Febi/TRW, если они не указали OE.  
Выборка сужается → \(n_i\)↓ → больше `manual` / слабее \(P^\*\).

**TecDoc-level DB:** платная, лицензируется на юрлицо, **не влезает** в бюджет ~€1500.

### 7.3. Частичные кроссы из описаний (Слой 6) — не «просто фича»

Продавцы пишут: «OE 1K0121251, аналог Nissens 65277».  
Regex/NER по description может достроить 20–40% связей.

**Ориентир цены:** +€500–700.  
**Условие запуска:** только если **замер** покажет, что выборка по чистому OE реально узкая.  
Это **письменное обещание клиенту проверить** — не roadmap-декор.

---

## 8. Замер на Prom — текущий драйвер проекта (MUST DO)

### 8.1. Зачем

Отвечает на один вопрос:

> Насколько узка выборка рынка, если искать **только по OE клиента**, без кроссов?

Если медианный \(n_i\) уже 5–10 usable offers — Слой 6 отложить.  
Если медианный \(n_i\) 0–2 — Слой 6 (или ручной process) критичен.

### 8.2. Протокол «30 позиций / ~2 часа»

**Выборка:**

1. 30 SKU из каталога клиента (xlsx).
2. Стратификация (обязательно):
   - 10 «ходовых» (если известны),
   - 10 «средних»,
   - 10 «подозрительно мёртвых / редких OE»,
   - разные категории (тормоза / подвеска / …).
3. Только позиции с валидным OE.

**Процедура на каждый SKU:**

1. Нормализовать OE.
2. Поиск на Prom по OE (как будет делать система).
3. Записать:
   - total raw hits,
   - after drop used,
   - after drop same KEMP dumpers,
   - usable for pricing \(n\),
   - brands/tiers present,
   - min/median/max raw,
   - qualitative: «видны ли OES/analogA без кросса?»,
   - time spent.
4. Вручную отметить: «на рынке точно есть сильные аналоги под **другим** артикулом?» (да/нет/неясно) — для оценки upside Слоя 6.

**Метрики итога:**

| Метрика | Формула / смысл |
|---|---|
| \(q_{oem}\) sample | доля 30 с валидным OE (ожид. ≈1.0 by construction) |
| \(\tilde{n}_{med}\) | median usable offers |
| \(\tilde{n}_{p10}\) | 10-й перцентиль usable |
| share \(n<2\) | доля «недостаточно рынка» |
| share high_spread_suspect | доля, где глазом видна смесь уровней |
| cross_gap_rate | доля, где аналоги «есть», но не по OE |

**Decision rule (предварительный):**

```text
IF median(n_usable) >= 4 AND share(n<2) <= 0.25:
    → Слой 6 НЕ покупать сейчас; строить L3–L5–L7
ELIF median(n_usable) <= 2 OR share(n<2) >= 0.40:
    → Слой 6 quant quant quant (пилот 30+30 с description parse)
ELSE:
    → partial: description-cross only for LOW_N SKUs
```

### 8.3. Как сделать замер инструментально (на базе Marko as-is)

Вариант A (быстрый, semi-manual):  
`python -m marko compare <product_url>` / search by OE через временный script.

Вариант B (правильный):  
одноразовый CLI:

```text
marko measure-oe --xlsx client.xlsx --sample 30 --out measure_30.json
```

который для OE делает search pages, дампит offers, **без** tiering productization.

**Важно:** текущий `match_offer` с brand equality **нельзя** использовать как proxy рынка одной детали.  
Для замера: **search by OE → keep all sellers**, classify tiers offline in spreadsheet if needed.

---

## 9. Расширения (после замера / за деньги / phase2)

### 9.1. Ближайшее, за деньги

| Фича | Суть | Условие |
|---|---|---|
| Частичные кроссы из описаний | parse multi-numbers in ads; expand \(\mathcal{M}_i\) | только после замера; +€500–700 orient |
| Autopro | 2-я площадка, тот же engine, другой parser | отдельный budget |
| Автопубликация | write prices back | опасно; sellable; strong confirm UX |
| 1С/BAS | ERP sync | enterprise |

### 9.2. Phase2 (отложено)

| Фича | Правило |
|---|---|
| Курсовая справка НБУ | **report only**, not input to \(P^{rec}\) |
| Telegram alerts | competitor price change events |
| История цен + графики | уже почти есть `price_observations` |

### 9.3. Multi-client horizon

| Фича | Комментарий |
|---|---|
| Общая кросс-база | единственный asset, который накапливается; **юридически/этически** — говорить клиенту честно, если данные с его рынка пойдут другим |
| Эластичность спроса | нужна таблица `price_changes` + продажи; при 3–5 sales/SKU/month — горизонт 12–18 мес. Сейчас **невозможно** честно |

---

## 10. Модель данных (to-build поверх Marko)

### 10.1. As-is таблицы (reuse)

- `users`, `workspaces`, `workspace_members`
- `marketplace_stores`, `workspace_stores`
- `listings`, `price_observations`
- `product_matches` (сейчас про listing↔listing; для Metis market offers может быть отдельной сущностью)
- `sync_runs`

### 10.2. Предлагаемые сущности Metis

```text
pricing_runs
  id, workspace_id, store_id, status, stage,
  params_json, started_at, finished_at, error,
  stats_json  # n_items, n_with_oe, n_recommendations, ...

pricing_run_items
  id, run_id, listing_id,
  oe_raw, oe_norm, category_key,
  own_price, currency,
  stock_mode,  # fresh|slow|dead|unset
  sales_weight,
  fair_price, conf, action, rec_price,
  delta, score, reason_code,
  debug_json

market_offers
  id, run_id, run_item_id,
  seller_external_id, seller_name,
  brand, name, url,
  price, currency, is_available,
  tier, tier_source, keep|drop_reason,
  adjusted_price,
  raw_json, observed_at

level_coefficients
  id, scope (category|global), category_key,
  tier, k, n_support, version, computed_at

tier_dictionary_versions
  version, payload_json, created_at

# client-side only ideally:
# stock_modes & costs may live in local encrypted storage
# if server-held cost is ever required: field-level encryption + ACL
```

### 10.3. Деньги

- `NUMERIC(14,2)` + `Decimal` в Python (уже convention Marko).  
- Не float для money path в production engine.

---

## 11. План реализации в коде (для ИИ-агента: порядок PR)

### PR-0. Замер (блокирующий, 1–2 дня)

1. CLI/script: sample 30 OE from xlsx or CSV.  
2. Search Prom by OE (reuse `HttpClient` + `parse_search`).  
3. **Do not** filter by brand equality.  
4. Export JSON/CSV metrics §8.  
5. Human decision on Layer 6.

### PR-1. Domain: OE + stock_mode + pricing run skeleton

1. Migration: `oe_norm` on listings or run_items; indexes.  
2. `pricing_runs` / `pricing_run_items` / `market_offers`.  
3. API: create run, get run status, get recommendations page.  
4. Worker task stub stages.

### PR-2. Xlsx ingest

1. Parse Prom 87-col export.  
2. Column mapping config (versioned).  
3. OE normalize + quality report \(q_{oem}\).  
4. Tests with fixture xlsx (anonymized).

### PR-3. Batch market collect

1. Celery group by chunks of OE.  
2. Rate limit, retries (reuse `HttpClient`).  
3. Persist raw offers.  
4. Progress on run.  
5. Idempotent re-run of failed OEs.

### PR-4. Tiering + coefficients

1. Tier dictionary v1.  
2. Used/same-brand filters.  
3. Category \(k\) estimation job.  
4. Unit tests on synthetic multi-tier markets (case 1K0698151E-like).

### PR-5. Fair price + confidence + modes

1. IQR + median.  
2. conf formula + reason codes.  
3. fresh-only-up / slow-dead-down.  
4. Golden tests: «OEM present must not force raise to OEM raw».

### PR-6. Ranking + links API

1. Score = Δ × weight.  
2. Payload with competitor links + excluded reasons.

### PR-7. Flutter Metis UI

1. Upload xlsx / start run.  
2. Progress.  
3. Recommendations table (sort by score).  
4. Filters: action, conf, category.  
5. Stock mode marking.  
6. Client-side cost field (local).  
7. Deep links open Prom.

### PR-8. Hardening for deploy

См. §13.

**Запрет агенту:** «упростить» Metis до `median(competitor prices)` или reuse `brands_compatible` as market filter. Это уничтожает продукт.

---

## 12. Тест-стратегия (математически значимые кейсы)

### 12.1. Unit (pricing pure functions)

| ID | Сценарий | Ожидание |
|---|---|---|
| T1 | prices {3200 oem, 2000 oes, 1400 A, 400 used} + k | used dropped; adjusted median << 3200 |
| T2 | other KEMP 700 present | dropped from \(P^\*\) |
| T3 | 3 points with 1 extreme outlier | IQR removes; median stable |
| T4 | n=1 | conf low → manual |
| T5 | fresh & P* < P_own | hold, not lower |
| T6 | dead & P* < P_own | lower allowed |
| T7 | high spread mixed tiers | manual + TIER_MIX |
| T8 | category k fallback to global | when n_cat < n_min |

### 12.2. Integration

- search parse still works (Apollo keys).  
- run state machine transitions.  
- partial failure: 1% OE fail does not fail whole run.

### 12.3. Regression vs Marko

- existing `test_matching.py`, `test_parsing.py`, import/auth tests green.  
- new pricing tests **do not** break catalog import.

### 12.4. Product acceptance with client

- 20 random raise recommendations: client clicks links, agrees ≥80%.  
- 0 cases where system recommended raise because of raw OEM price without adjust.

---

## 13. Усовершенствование для конечного деплоя (production readiness)

Ниже — что нужно, чтобы Metis/Marko был **не demo compose**, а выкладка одному клиенту / small SaaS.

### 13.1. Целевая prod-архитектура

```text
Internet
   │
   ▼
[TLS terminator / reverse proxy]  (Caddy / Traefik / Nginx / cloud LB)
   │
   ├─► frontend (Flutter web static)  CDN optional
   │
   └─► api (uvicorn/gunicorn+uvicorn workers)
            │
            ├─► PostgreSQL (managed preferred)
            ├─► Redis (managed / private net)
            └─► worker × N  +  beat × 1
```

**Принципы:**

- API stateless.  
- Worker horizontally scalable, but **scrape concurrency capped globally** (token bucket in Redis).  
- DB single source of truth.  
- Secrets not in image layers / git.

### 13.2. Compose → prod compose / K8s

As-is `compose.yaml`: dev defaults, open ports, `ENVIRONMENT: development`.

**To-build:**

| Файл / слой | Назначение |
|---|---|
| `compose.prod.yaml` | no host publish of db/redis; restart policies; resource limits |
| `.env.prod` (not committed) | secrets |
| reverse proxy service | TLS, HTTP→HTTPS, security headers |
| separate networks | `frontend` public, `backend` private |

Минимум для single-VPS:

```text
docker compose -f compose.yaml -f compose.prod.yaml up -d
```

### 13.3. Secrets & config

| Item | Dev | Prod |
|---|---|---|
| `POSTGRES_PASSWORD` | `marko` | strong random |
| `FIREBASE_PROJECT_ID` | dev project | prod project (or same with prod domains) |
| `CORS_ORIGINS` | localhost | exact app origin(s) |
| `API_BASE_URL` (Flutter define) | localhost:8000 | `https://api.domain` |
| DB URL | compose internal | private DNS |

Flutter Firebase + API URL — **build-time** (`--dart-define`).  
CI должен собирать frontend с prod defines; rebuild on change.

### 13.4. TLS, cookies, auth

- HTTPS only for app + API.  
- Firebase authorized domains: production host.  
- Google OAuth branding / production audience when leaving testing.  
- API verifies RS256 JWT as now; ensure clock sync on server.  
- Rate-limit `/api/v1` (proxy or middleware) against token stuffing.

### 13.5. Database production

- Managed Postgres 17 if possible (backups, PITR).  
- Alembic in release pipeline: migrate before traffic.  
- **Never** `docker compose down -v` on prod.  
- Indexes for Metis: `(oe_norm)`, `(run_id, score DESC)`, `(run_id, action)`.  
- Retention policy for `market_offers.raw_json` (size!) — e.g. keep raw 30–90 days, keep aggregates forever.  
- `NUMERIC` money only.

### 13.6. Redis / Celery

- Redis AOF or managed; password; bind private.  
- Celery:
  - queues: `import`, `market`, `pricing` (priorities),
  - `task_acks_late=True`, `worker_prefetch_multiplier=1` for long scrape tasks,
  - time limits / soft limits,
  - result expiry,
  - beat single instance (redlock or one replica).  
- Dead-letter / failed task visibility in admin or logs.

### 13.7. Scraper production constraints (критично для 4901 SKU)

| Risk | Mitigation |
|---|---|
| Ban / antibot | polite delay, UA rotate (есть), exponential backoff (есть), global concurrency cap |
| Apollo schema change | parser contract tests + canary sample daily |
| Partial outage | checkpoint per OE; resume |
| Legal/ToS | client agreement; rate limits; store only needed fields |
| Runtime hours | night window jobs; progress UI |

**Не** поднимать concurrency «чтобы быстрее» без cap и мониторинга 429.

### 13.8. Observability

Minimum:

- structured logs (JSON) with `request_id`, `run_id`, `oe`  
- metrics: run duration, success rate, offers/OE distribution, parser errors, HTTP 429 count  
- health: already `live`/`ready` — extend ready with DB+Redis  
- error tracking (Sentry) for api+worker+frontend  
- uptime check on `/health/live`

### 13.9. Security checklist

- [ ] No secrets in git / images  
- [ ] DB/Redis not public  
- [ ] CORS tight  
- [ ] Auth on all mutating routes (as-is pattern)  
- [ ] File upload xlsx: size limit, content-type, virus scan optional, parse in worker not API thread  
- [ ] SSRF: store URLs only prom.ua host allowlist (Seller.from_url already pattern-based — enforce at API)  
- [ ] Cost data: prefer client-only; if server — encryption + no shared logs  
- [ ] Dependency pinning / audit (`uv.lock` already)  
- [ ] Non-root containers  
- [ ] Read-only rootfs where possible  

### 13.10. Frontend deploy

- Flutter web release build in Docker (as-is)  
- Cache headers: hashed assets long-cache; `index.html` no-cache  
- SPA fallback nginx (check `frontend/nginx.conf`)  
- Android: only if client needs; web may be enough for single seller  
- Windows: web/PWA (README strategy)  

### 13.11. Backup & DR

- Nightly DB dump encrypted offsite  
- Restore drill once before client go-live  
- Run artifacts (recommendations) exportable to xlsx for client offline  

### 13.12. Performance targets (single client N≈5000)

| Stage | Target |
|---|---|
| xlsx ingest | < 2 min |
| market collect | < 6–12 h wall with polite limits (or overnight) |
| pricing compute | < 5 min pure CPU after data in DB |
| UI list 50 rows | < 300 ms API p95 |

### 13.13. Multi-tenant readiness (if SaaS later)

As-is: workspace isolation for stores.  
Must enforce:

- every query filtered by `workspace_id` (audit all repos),  
- no cross-tenant OE cache leak **unless** explicit shared cross DB agreement,  
- quota per workspace on runs/day.

### 13.14. Go-live checklist (один клиент)

1. Замер 30 OE выполнен, decision по Слою 6 зафиксирован письменно.  
2. Xlsx import + \(q_{oem}\) report.  
3. Full run on subset (200 SKU) → client trust review.  
4. Full run 4901 overnight.  
5. UI recommendations accepted.  
6. Prod TLS + backups + monitoring green.  
7. Support runbook: parser broken, 429 storm, rerun failed OEs.

---

## 14. Карта «продуктовый шаг → код → математика → статус»

| # | Продукт | Математика / правило | Код as-is | Статус |
|---|---|---|---|---|
| 1 | Каталог | \(q_{oem}\), normalize OE | immutable XLSX snapshot + row errors | implemented |
| 2 | Рынок | \(\mathcal{M}_i\) by OE | batch Celery collection + capture/checkpoint | implemented |
| 3 | Уровни | \(\tau(j)\), exclusions | append-only classifier + manual override | implemented |
| 4 | \(k\) | paired-OE median + shrinkage | simple + LOO hierarchical models | implemented |
| 5 | \(P^\*\) | IQR/MAD + median \(\tilde{P}\) | pure Decimal pricing engine | implemented |
| 6 | Режимы | fresh↑ only; stale/dead↓ | cost/floor/auth gates | implemented |
| 7 | conf | decomposed scores + hard floors | geometric/min + true half-life | implemented |
| 8 | rank | economic effect by score type | separate unit-safe queues | implemented |
| 9 | links | trust | used-evidence endpoint + Flutter drawer | implemented |
| — | cost | manual context, not fair price | append-only override + audit snapshot | implemented |
| — | Layer6 | description multi-OE | **нет** | blocked on measure |

---

## 15. Анти-паттерны (агенту запрещено)

1. Считать \(P^\* = \mathrm{mean/median}(\text{raw competitor prices})\) без tiering.  
2. Использовать `brands_compatible` как фильтр рыночных оферт одной детали.  
3. Подмешивать себестоимость / sunk cost / курс НБУ в \(P^\*\).  
4. Советовать `lower` на `fresh`.  
5. Автопубликовать цены «для красоты демо».  
6. Тянуть TecDoc «потому что правильно» без бюджета/лицензии.  
7. Строить Слой 6 до замера 30 OE.  
8. Синхронно парсить 4901 OE в API request.  
9. Хранить секреты Firebase service account «на всякий» (текущая модель — public JWKS verify; не ломать).  
10. Упрощать conf до «если есть 1 конкурент — ок».  

---

## 16. Краткая executive summary

**Metis** — pricing decision engine для продавца бюджетных автозапчастей (KEMP) на Prom.ua: один прогон → где поднять, где слить, в каком порядке, с ссылками и отказом при низкой уверенности.

**Ядро ценности** — не парсер, а **приведение чужих цен к уровню клиента** через категорийные коэффициенты + робастная медиана + безопасные режимы стока.

**Marko** уже даёт: auth/workspaces, immutable XLSX/OE snapshots, Prom Apollo
parser, rate-limited async runs, append-only evidence/tiering, обе coefficient
models, leakage-safe KEMP normalization, robust fair price, confidence,
fresh/stale/dead modes, typed economic priority, audit API и operator UI.

**До production rollout остаются внешние gates:** labeled holdout, утверждённые
pilot thresholds, live full-stack/Prom smoke run, monitoring и operational
hardening. Это не отсутствие pricing engine, а проверка его evidence на реальном
рынке.

**Сейчас двигает проект:** замер 30 позиций на Prom по чистому OE (~2 часа), а не список фич.  
От него зависит единственное платное расширение на столе — **частичные кроссы из описаний**.

---

## 17. Appendix A — псевдокод fair price (reference implementation sketch)

```python
def fair_price(offers, k_by_tier, alpha=1.5, n_min=2):
    adjusted = []
    for o in offers:
        if o.drop_reason:  # used, same_brand_kemp, own, ...
            continue
        k = k_by_tier[o.tier]
        if k is None or k <= 0:
            continue
        adjusted.append(o.price / k)
    if len(adjusted) < n_min:
        return None, "LOW_N", adjusted
    rob = iqr_filter(adjusted, alpha=alpha)
    if not rob:
        rob = adjusted
    p_star = median(rob)
    spread = (max(rob) - min(rob)) / p_star if p_star else inf
    conf = sample_phi(len(rob)) * spread_phi(spread) * tier_quality_phi(offers)
    return p_star, conf, rob


def recommend(p_own, p_star, conf, stock_mode, theta=0.6, eps=0.03):
    if p_star is None or conf < theta:
        return "manual", None
    if stock_mode == "fresh":
        if p_star > p_own * (1 + eps):
            return "raise", p_star
        return "hold", None
    # slow / dead
    beta = 0.95 if stock_mode == "slow" else 0.85
    p_rec = p_star * beta
    if p_rec < p_own * (1 - eps):
        return "lower", p_rec
    return "hold", None
```

---

## 18. Appendix B — файлы репозитория (навигация агента)

```text
marko — копия/
  compose.yaml
  README.md
  docs/
    architecture.md
    database.md
    metis.md                 ← этот документ
  backend/src/marko/
    api/                     # HTTP only
    core/config.py
    infrastructure/db/models.py
    parsers/prom/            # client, parser, gateway
    services/
      catalog_import.py
      matching.py            # NOT final Metis pricing
      ...
    worker/tasks/
  frontend/lib/features/
    auth/, dashboard/, stores/
  scripts/prom_cli.py
```

---

## 19. Appendix C — decision log (заполнить после замера)

| Дата | Выборка | median n_usable | share n&lt;2 | Decision Layer6 | Подпись |
|---|---|---:|---:|---|---|
| _TBD_ | 30 SKU | _TBD_ | _TBD_ | build / skip / partial | |

---

**Конец документа.**  
При реализации агент обязан: (1) не упрощать ядро tiering, (2) не игнорировать замер, (3) не смешивать sunk cost с recommendation, (4) сохранять client-only себестоимость, (5) опираться на этот файл как на product+math source of truth.
