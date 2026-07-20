# ADR: защита себестоимости в Yuri V1

- ADR ID: `PROMPT_15_016_COST_PRIVACY_ADR_2026-07-18`
- Статус: `ACCEPTED_IMPLEMENTED`
- Выбранный режим: `SERVER_SIDE_ENCRYPTED`
- Владелец решения: Юрий / владелец данных
- Основание: прямое решение пользователя от 2026-07-18 — реализовать серверное шифрование
- Область: ручной ввод, хранение, проверка решения ниже себестоимости, удаление и аудит изменений

## Решение

Себестоимость разрешено передавать API только при активном режиме
`SERVER_SIDE_ENCRYPTED` и корректно настроенном внешнем keyring. До шифрования
значение существует в памяти процесса приложения, поэтому этот режим защищает
данные в БД, snapshots, responses и обычных журналах, но не обещает скрыть их от
полностью скомпрометированного application runtime или администратора хоста.

Справедливая рыночная цена по-прежнему рассчитывается без себестоимости. После
расчёта сервер расшифровывает её только для двух безопасных операций:

1. сформировать булев признак `recommended_price_below_cost`;
2. потребовать явное ручное подтверждение решения ниже себестоимости.

Себестоимость не становится жёстким ценовым floor и не входит в сортировку
экономического потенциала.

## Криптографический формат

- алгоритм: `AES-256-GCM`;
- nonce: новые случайные 96 бит для каждой записи;
- plaintext: канонический положительный `Decimal` UAH, не более двух знаков после запятой;
- authenticated associated data связывает ciphertext с `workspace_id`,
  `catalog_item_id`, неизменяемым `record_id`, `key_id`, версией формата и `UAH`;
- ключ шифрования не хранится в БД, migration или repository;
- `key_id` хранится рядом с ciphertext и не считается секретом;
- одна и та же себестоимость при повторной записи получает другой nonce и другой ciphertext;
- подмена ciphertext, nonce, tenant, товара или record ID приводит к ошибке аутентификации.

Реализация: `backend/src/marko/core/cost_encryption.py`.

## Хранение и аудит

Migration `20260718_0013` создаёт append-only таблицу
`catalog_item_cost_records`:

- `SET` содержит только ciphertext, nonce, key ID, алгоритм и версию формата;
- `CLEAR` — аудируемый tombstone без ciphertext;
- глобальный identity `sequence_no` определяет последнюю запись без зависимости
  от одинаковых timestamps;
- уникальность `(key_id, nonce)` страхует от случайного повторного nonce;
- DB constraints проверяют действие, алгоритм, версию и размер payload;
- каждая запись связана с workspace, catalog item и оператором.

Удаление не раскрывает старое значение и не переписывает историю. Физическое
удаление исторических ciphertext относится к отдельной retention policy.

## Key management и rotation

Runtime читает:

- `COST_ENCRYPTION_ACTIVE_KEY_ID`;
- `COST_ENCRYPTION_KEYS_JSON`, где каждому key ID соответствует base64url-ключ
  длиной ровно 32 байта.

Новый ciphertext всегда использует active key. Старые ключи остаются в keyring
только для чтения старых записей. Rotation выполняется так:

1. добавить новый ключ рядом со старым;
2. назначить его active;
3. убедиться, что новые записи используют новый key ID, а старые читаются;
4. при необходимости выполнить отдельный контролируемый re-encryption;
5. удалять старый ключ только после подтверждённой миграции и recovery drill.

Если режим выбран, но keyring отсутствует, повреждён или не содержит active key,
приложение не стартует. Секрет представлен как `SecretStr` и не попадает в обычный
`repr(Settings)`.

## API и UI

Разрешённый write endpoint — ручной catalog override. Он принимает `cost` только
в зашифрованном режиме и никогда не возвращает raw value. Ответы содержат только:

- `cost_configured`;
- `cost_privacy_mode`;
- `recommended_price_below_cost` в recommendation context;
- ручные `allow_below_cost` и `warning_confirmed`.

Побочный `/pricing/evaluate` запрещает raw cost, чтобы значение не попадало в
неперсистентный расчётный payload. Неизвестные legacy поля, включая
`below_cost_floor`, отклоняются. Validation errors удаляют исходный `input` и не
отражают ошибочно введённую себестоимость.

Flutter:

- не загружает текущее raw value обратно;
- позволяет ввести новое значение или создать `CLEAR` tombstone;
- показывает только факт наличия себестоимости;
- требует явного подтверждения, если сохранённая себестоимость выше рекомендации;
- не включает raw cost в decision payload.

## Legacy plaintext

Старые nullable-колонки `cost`, существовавшие до этого ADR, не удалены
деструктивно и не мигрированы автоматически. Активный Yuri V1 flow их игнорирует,
а public serializers и replay boundaries их редактируют. Их очистка требует
отдельно утверждённых retention, backup и rollback правил.

## Threat model и честные границы

| Actor / boundary | Результат |
|---|---|
| Другой tenant | запросы и записи workspace-scoped |
| Обычный DB reader | видит ciphertext и metadata, но не ключ |
| API response / replay / validation error | raw cost отсутствует |
| UI после сохранения | видит только `cost_configured` |
| Скомпрометированный DB без keyring | plaintext не раскрывается |
| Скомпрометированный runtime или хост с keyring | может получить plaintext; этот ADR не обещает enclave-level secrecy |
| Потерянный active key без backup | старые значения невосстановимы |
| Компрометация keyring вместе с DB | защита at-rest исчерпана; требуется rotation и incident response |

## Проверки

`backend/tests/test_cost_encryption.py` доказывает:

- round-trip без silent rounding;
- уникальные nonce/ciphertext;
- AAD isolation между tenant/item/record;
- отказ при tampering;
- чтение старого ключа после rotation;
- fail-closed invalid keyring;
- отсутствие plaintext в persistence model и Settings representation;
- запрет raw cost в неперсистентном pricing API.

`frontend/test/pricing_encrypted_cost_dialog_test.dart` проверяет ввод, замену,
очистку и подтверждение below-cost без возврата исходного значения.

`scripts/prove_encrypted_cost_runtime.py` выполнил PostgreSQL transaction proof
через реальную migration `0013`, расшифровал synthetic value сервисным кодом и
откатил транзакцию; сохранённых synthetic records после proof — ноль.

## Runtime state

Код, migration и локальный Docker image готовы. Локальный `.env` намеренно не
содержит автоматически сгенерированный секрет и остаётся в `UNDECIDED`, поэтому
реальная форма ввода fail-closed до явного provisioning ключа. Это больше не
бизнес-блокер `R-05`; это операционный deployment gate, который нельзя закрывать
публикацией ключа в repository или отчёте.
