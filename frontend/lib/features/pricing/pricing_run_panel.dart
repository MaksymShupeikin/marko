import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/app_language.dart';
import '../../core/app_theme.dart';
import '../../core/marko_ui.dart';
import '../../core/session_expiry.dart';
import '../catalog/catalog_import_api.dart';
import '../catalog/catalog_import_models.dart';
import 'pricing_api.dart';
import 'pricing_models.dart';
import 'pricing_run_attempt_store.dart';

typedef PricingRunDelay = Future<void> Function(Duration duration);
typedef PricingRunUpdate = void Function(PricingRunSummary run);

class PricingRunPollingLimitExceeded implements Exception {
  const PricingRunPollingLimitExceeded(this.lastRun, this.attempts);

  final PricingRunSummary lastRun;
  final int attempts;
}

Future<PricingRunSummary> pollPricingRun({
  required Future<PricingRunSummary> Function(String id) fetch,
  required String runId,
  required PricingRunUpdate onUpdate,
  int maxAttempts = 20,
  Duration initialDelay = const Duration(seconds: 1),
  Duration maxDelay = const Duration(seconds: 15),
  PricingRunDelay delay = Future<void>.delayed,
}) async {
  if (maxAttempts < 1) {
    throw ArgumentError.value(maxAttempts, 'maxAttempts', 'must be positive');
  }
  var wait = initialDelay;
  PricingRunSummary? last;
  for (var attempt = 1; attempt <= maxAttempts; attempt += 1) {
    last = await fetch(runId);
    onUpdate(last);
    if (last.isFinished) return last;
    if (attempt < maxAttempts) {
      await delay(wait);
      final doubled = wait * 2;
      wait = doubled > maxDelay ? maxDelay : doubled;
    }
  }
  throw PricingRunPollingLimitExceeded(last!, maxAttempts);
}

/// Насколько велик прогон, который просит владелец.
///
/// Полный каталог — самый дорогой режим: для магазина в несколько тысяч SKU
/// это часы скрейпинга и весь месячный бюджет. Пока он был единственным
/// вариантом, «запустить меньше» просто не существовало как действие.
/// Ограниченные когорты берут начало импорта в порядке файла — выбор
/// воспроизводимый и объяснимый, в отличие от «каких-нибудь 300 позиций».
enum PricingRunScopeChoice {
  fullCatalog(null),
  first300(300),
  first500(500);

  const PricingRunScopeChoice(this.itemLimit);

  /// `null` — весь каталог; иначе граница когорты.
  final int? itemLimit;

  bool get isFullCatalog => itemLimit == null;

  String label(BuildContext context) => switch (itemLimit) {
    null => context.localized(ru: 'Весь каталог', uk: 'Весь каталог'),
    final limit => context.localized(
      ru: 'Первые $limit позиций',
      uk: 'Перші $limit позицій',
    ),
  };

  /// Название области внутри подтверждения: владелец соглашается на конкретную
  /// область, а не на «расчёт».
  String confirmationName(BuildContext context) => switch (itemLimit) {
    null => context.localized(ru: 'весь каталог', uk: 'весь каталог'),
    final limit => context.localized(
      ru: 'первые $limit позиций импорта',
      uk: 'перші $limit позицій імпорту',
    ),
  };
}

class PricingRunPanel extends ConsumerStatefulWidget {
  const PricingRunPanel({
    required this.canAdministerWorkspace,
    required this.onRunFinished,
    super.key,
  });

  final bool canAdministerWorkspace;
  final VoidCallback onRunFinished;

  @override
  ConsumerState<PricingRunPanel> createState() => _PricingRunPanelState();
}

class _PricingRunPanelState extends ConsumerState<PricingRunPanel> {
  bool _loading = true;

  /// A start or cancel request is in flight. Polling is deliberately *not*
  /// part of this: a run polled for ten minutes is not a ten-minute mutation,
  /// and folding the two together left cancel disabled for the whole run.
  bool _mutating = false;
  bool _polling = false;
  String? _polledRunId;
  int _pollGeneration = 0;
  String? _error;

  /// Долговечную идентичность попытки не удалось ни прочитать, ни записать, и
  /// старт поэтому не состоялся. Состояние отдельное от [_error]: это не сбой
  /// расчёта, а условие, которое владелец может снять сам.
  bool _attemptStorageBlocked = false;
  String? _selectedBatchId;
  PricingRunScopeChoice _scope = PricingRunScopeChoice.fullCatalog;

  List<CatalogImportBatch> _imports = const [];
  List<PricingRunSummary> _runs = const [];
  PricingRunSummary? _active;

  PricingApi get _pricing => ref.read(pricingApiProvider);
  CatalogImportApi get _catalog => ref.read(catalogImportApiProvider);
  PricingRunAttemptStore get _attempts =>
      ref.read(pricingRunAttemptStoreProvider);

  bool get _hasActiveRun => _active != null && !_active!.isFinished;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    if (mounted) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      // Оба запроса уходят вместе — но ждать их порознь нельзя: когда первый
      // отказывает, у второго отказа уже нет ожидающего, и он всплывает как
      // необработанная асинхронная ошибка. Один мёртвый токен валит оба.
      final results = await Future.wait<Object?>([
        _pricing.listRuns(),
        _catalog.list(),
      ]);
      if (!mounted) return;
      final runs = results[0] as List<PricingRunSummary>;
      final imports = results[1] as List<CatalogImportBatch>;
      final eligible = imports
          .where((batch) => batch.isSuccess)
          .toList(growable: false);
      final active = runs.where((run) => !run.isFinished).firstOrNull;
      setState(() {
        _runs = runs;
        _imports = eligible;
        _active = active ?? runs.firstOrNull;
        _selectedBatchId = eligible.any((batch) => batch.id == _selectedBatchId)
            ? _selectedBatchId
            : eligible.firstOrNull?.id;
        _loading = false;
      });
      // A run started before this page was opened (or before a browser reload)
      // is still working. Without resuming here the panel froze on whatever
      // status the list happened to return.
      _ensurePolling(active);
    } catch (error) {
      if (!mounted) return;
      setState(() => _loading = false);
      _fail(error);
    }
  }

  /// Единственная воронка для всего, что может вернуть этот экран.
  ///
  /// Загрузка, предпросмотр, старт, опрос статуса и отмена — пять разных
  /// запросов и один и тот же мёртвый токен. Пока каждый из них печатал
  /// `error.toString()`, истёкшая сессия выглядела как сбой расчёта: красная
  /// полоса с английским текстом бэкенда и кнопки, которые оставались нажимаемы
  /// и не могли сработать.
  void _fail(Object error) {
    if (!mounted) return;
    if (ref.classifySessionExpiry(error)) {
      setState(() => _error = null);
      return;
    }
    setState(() => _error = error.toString());
  }

  Future<void> _start() async {
    final batchId = _selectedBatchId;
    if (batchId == null || _mutating || _hasActiveRun) return;

    final choice = _scope;
    // Область замораживается до подтверждения, чтобы владелец соглашался на
    // названное число позиций, а не на «расчёт по импорту».
    setState(() {
      _mutating = true;
      _error = null;
      _attemptStorageBlocked = false;
    });
    PricingRunPreview? preview;
    var itemIds = const <String>[];
    try {
      final limit = choice.itemLimit;
      if (limit != null) {
        itemIds = await _catalog.listItemIds(batchId, limit: limit);
      }
      preview = limit == null
          ? await _pricing.previewRun(batchId)
          : itemIds.isEmpty
          ? null
          : await _pricing.previewRun(
              batchId,
              scopeMode: 'EXPLICIT_ITEMS',
              catalogItemIds: itemIds,
            );
      if (preview == null && mounted) {
        setState(() {
          _error = context.localized(
            ru: 'В этом импорте нет позиций для расчёта.',
            uk: 'У цьому імпорті немає позицій для розрахунку.',
          );
        });
      }
    } catch (error) {
      _fail(error);
    } finally {
      if (mounted) setState(() => _mutating = false);
    }
    final scope = preview;
    if (scope == null || !mounted) return;

    final excluded = scope.excludedItems > 0
        ? context.localized(
            ru: ' Отклонено позиций: ${scope.excludedItems}.',
            uk: ' Відхилено позицій: ${scope.excludedItems}.',
          )
        : '';
    // Числа берутся из предпросмотра именно этой области, а не из доли
    // полного каталога: сколько позиций пригодно, знает только сервер.
    final confirmed = await _confirm(
      titleRu: 'Запустить расчёт цен?',
      titleUk: 'Запустити розрахунок цін?',
      bodyRu:
          'Область: ${choice.confirmationName(context)}. '
          'В расчёт попадёт позиций: ${scope.eligibleItems}.$excluded '
          'В худшем случае это займёт около ${scope.worstCaseMinutes} мин. '
          'Расчёт не меняет цены на Prom.ua автоматически.',
      bodyUk:
          'Область: ${choice.confirmationName(context)}. '
          'У розрахунок потрапить позицій: ${scope.eligibleItems}.$excluded '
          'У найгіршому разі це триватиме близько ${scope.worstCaseMinutes} хв. '
          'Розрахунок не змінює ціни на Prom.ua автоматично.',
      actionRu: 'Запустить',
      actionUk: 'Запустити',
    );
    if (!confirmed || !mounted) return;
    setState(() {
      _mutating = true;
      _error = null;
    });
    final identity = _startIdentity(batchId, scope);
    // Хранилище попыток переживает этот виджет, поэтому ссылка на него берётся
    // пока он ещё смонтирован.
    final attempts = _attempts;
    // Ключ резервируется до запроса и отдельно от него. Прогон, попытку
    // которого негде записать, не запускается вовсе: без записи повтор после
    // перезагрузки принесёт другой ключ, и владелец оплатит второй скрейпинг
    // каталога за одно нажатие.
    final String attemptKey;
    try {
      attemptKey = await attempts.reserve(identity);
    } on PricingRunAttemptUnavailable {
      if (!mounted) return;
      setState(() {
        _mutating = false;
        _attemptStorageBlocked = true;
      });
      return;
    }
    PricingRunSummary? started;
    try {
      started = await _pricing.startRun(
        batchId,
        scopeMode: scope.scopeMode,
        catalogItemIds: itemIds,
        // Подтверждение владельца, а не умолчание клиента.
        confirmFullCatalog: scope.requiresFullCatalogConfirmation,
        idempotencyKey: attemptKey,
        previewToken: scope.previewToken,
      );
    } catch (error) {
      _fail(error);
    } finally {
      if (mounted) setState(() => _mutating = false);
    }
    final run = started;
    if (run == null) return;
    // Попытка закрыта — и закрыть её надо независимо от того, пережил ли виджет
    // ответ: иначе потраченный ключ склеит следующий осознанный прогон с этим.
    await attempts.release(identity);
    if (!mounted) return;
    setState(() {
      _active = run;
      _runs = [run, ..._runs.where((item) => item.id != run.id)];
    });
    // Polling outlives the start request; the panel stays interactive.
    await _poll(run);
  }

  /// Что делает попытку «той же»: тот же импорт, тот же режим области, тот же
  /// каталог. Ключ идемпотентности выводится не из этой строки, а из записанной
  /// случайности, привязанной к ней, — сама по себе область у повторного
  /// прогона совпадает всегда.
  String _startIdentity(String batchId, PricingRunPreview scope) =>
      'run:$batchId:${scope.scopeMode}:${scope.scopeHash}'
      ':${scope.catalogSnapshotHash}';

  void _ensurePolling(PricingRunSummary? run) {
    if (run == null || run.isFinished) return;
    if (_polling && _polledRunId == run.id) return;
    unawaited(_poll(run));
  }

  Future<void> _poll(PricingRunSummary run) async {
    final generation = ++_pollGeneration;
    if (mounted) {
      setState(() {
        _polling = true;
        _polledRunId = run.id;
      });
    }
    try {
      final finished = await pollPricingRun(
        fetch: _pricing.getRun,
        runId: run.id,
        onUpdate: (updated) {
          if (!mounted || generation != _pollGeneration) return;
          setState(() {
            _active = updated;
            _runs = [updated, ..._runs.where((item) => item.id != updated.id)];
          });
        },
      );
      if (generation != _pollGeneration) return;
      if (finished.isFinished) widget.onRunFinished();
    } on PricingRunPollingLimitExceeded catch (error) {
      if (!mounted || generation != _pollGeneration) return;
      setState(() {
        _error = context.localized(
          ru: 'Автообновление остановлено после ${error.attempts} попыток. Расчёт не отменён — нажмите «Обновить статус».',
          uk: 'Автооновлення зупинено після ${error.attempts} спроб. Розрахунок не скасовано — натисніть «Оновити статус».',
        );
      });
    } catch (error) {
      // A failed status read must not escape as an unhandled async error, and
      // must not look like a failed run.
      if (!mounted || generation != _pollGeneration) return;
      _fail(error);
    } finally {
      if (mounted && generation == _pollGeneration) {
        setState(() {
          _polling = false;
          _polledRunId = null;
        });
      }
    }
  }

  Future<void> _cancel() async {
    final run = _active;
    if (run == null || !run.isCancellable || _mutating) return;
    final confirmed = await _confirm(
      titleRu: 'Отменить расчёт?',
      titleUk: 'Скасувати розрахунок?',
      bodyRu:
          'Уже сохранённые результаты останутся доступны, новые позиции обрабатываться не будут.',
      bodyUk:
          'Уже збережені результати залишаться доступними, нові позиції не оброблятимуться.',
      actionRu: 'Отменить расчёт',
      actionUk: 'Скасувати розрахунок',
    );
    if (!confirmed || !mounted) return;
    setState(() {
      _mutating = true;
      _error = null;
    });
    PricingRunSummary? updated;
    try {
      updated = await _pricing.cancelRun(run.id);
    } catch (error) {
      _fail(error);
    } finally {
      if (mounted) setState(() => _mutating = false);
    }
    final cancelled = updated;
    if (cancelled == null || !mounted) return;
    setState(() {
      _active = cancelled;
      _runs = [cancelled, ..._runs.where((item) => item.id != cancelled.id)];
    });
    // The backend only records the request; keep watching until a worker
    // actually finalises the run.
    _ensurePolling(cancelled);
  }

  Future<bool> _confirm({
    required String titleRu,
    required String titleUk,
    required String bodyRu,
    required String bodyUk,
    required String actionRu,
    required String actionUk,
  }) async {
    return await showDialog<bool>(
          context: context,
          builder: (dialogContext) => AlertDialog(
            title: Text(dialogContext.localized(ru: titleRu, uk: titleUk)),
            content: Text(dialogContext.localized(ru: bodyRu, uk: bodyUk)),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext, false),
                child: Text(dialogContext.localized(ru: 'Назад', uk: 'Назад')),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(dialogContext, true),
                child: Text(
                  dialogContext.localized(ru: actionRu, uk: actionUk),
                ),
              ),
            ],
          ),
        ) ??
        false;
  }

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    // Мёртвый токен — состояние приложения, а не этой панели: 401 мог прийти
    // из экспорта или из списка рекомендаций, и запускать расчёт после него
    // так же бессмысленно.
    final sessionExpired = ref.watch(markoSessionExpiredProvider);
    return MarkoPanel(
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Wrap(
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 12,
            runSpacing: 8,
            children: [
              Text(
                context.localized(
                  ru: 'Ценовой расчёт',
                  uk: 'Ціновий розрахунок',
                ),
                style: Theme.of(context).textTheme.titleMedium,
              ),
              OutlinedButton.icon(
                key: const ValueKey('pricing-run-refresh'),
                onPressed: _loading || _mutating || sessionExpired
                    ? null
                    : _load,
                icon: const Icon(Icons.refresh_rounded, size: 18),
                label: Text(
                  context.localized(
                    ru: 'Обновить статус',
                    uk: 'Оновити статус',
                  ),
                ),
              ),
            ],
          ),
          // Страница, на которой панель живёт, отвечает за истёкшую сессию
          // сама — и одного ответа достаточно.
          if (sessionExpired && !MarkoSessionExpiryAnswered.above(context)) ...[
            const SizedBox(height: 12),
            const MarkoSessionExpiredMessage(
              key: ValueKey('pricing-run-session-expired'),
            ),
          ],
          if (_loading) ...[
            const SizedBox(height: 14),
            const LinearProgressIndicator(),
          ] else ...[
            const SizedBox(height: 12),
            if (_active == null)
              Text(
                context.localized(
                  ru: 'Расчёт ещё не запускался.',
                  uk: 'Розрахунок ще не запускався.',
                ),
                style: Theme.of(
                  context,
                ).textTheme.bodyMedium?.copyWith(color: colors.muted),
              )
            else
              _RunStatus(
                run: _active!,
                // The shown run is the newest unfinished one, which need not be
                // the import selected in the picker below. Without naming it,
                // the two read as one statement about one import.
                importName: _imports
                    .where((batch) => batch.id == _active!.importBatchId)
                    .map((batch) => batch.filename)
                    .firstOrNull,
              ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              MarkoInlineMessage(
                message: _error!,
                tone: MarkoMessageTone.error,
              ),
            ],
            if (_attemptStorageBlocked) ...[
              const SizedBox(height: 12),
              MarkoInlineMessage(
                key: const ValueKey('pricing-run-attempt-storage-blocked'),
                message: context.localized(
                  ru:
                      'Расчёт не запущен. Браузер не дал сохранить номер попытки, '
                      'а без него повтор после перезагрузки страницы создал бы '
                      'второй платный прогон того же каталога. Разрешите сайту '
                      'хранить данные (в приватном окне это обычно запрещено) и '
                      'повторите запуск.',
                  uk:
                      'Розрахунок не запущено. Браузер не дав зберегти номер спроби, '
                      'а без нього повтор після перезавантаження сторінки створив би '
                      'другий платний прогін того самого каталогу. Дозвольте сайту '
                      'зберігати дані (у приватному вікні це зазвичай заборонено) і '
                      'повторіть запуск.',
                ),
                tone: MarkoMessageTone.warning,
                action: TextButton(
                  key: const ValueKey('pricing-run-attempt-storage-retry'),
                  onPressed: _mutating || sessionExpired ? null : _start,
                  child: Text(
                    context.localized(
                      ru: 'Повторить запуск',
                      uk: 'Повторити запуск',
                    ),
                  ),
                ),
              ),
            ],
            if (widget.canAdministerWorkspace) ...[
              const SizedBox(height: 14),
              LayoutBuilder(
                builder: (context, constraints) {
                  final selector = DropdownButtonFormField<String>(
                    key: const ValueKey('pricing-run-import-batch'),
                    initialValue: _selectedBatchId,
                    isExpanded: true,
                    decoration: InputDecoration(
                      labelText: context.localized(
                        ru: 'Импорт каталога',
                        uk: 'Імпорт каталогу',
                      ),
                    ),
                    items: _imports
                        .map(
                          (batch) => DropdownMenuItem(
                            value: batch.id,
                            child: Text(
                              '${batch.filename} · ${batch.importedRows}/${batch.totalRows}',
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                        )
                        .toList(growable: false),
                    onChanged: _mutating
                        ? null
                        : (value) => setState(() => _selectedBatchId = value),
                  );
                  final scopeSelector =
                      DropdownButtonFormField<PricingRunScopeChoice>(
                        key: const ValueKey('pricing-run-scope'),
                        initialValue: _scope,
                        isExpanded: true,
                        decoration: InputDecoration(
                          labelText: context.localized(
                            ru: 'Область расчёта',
                            uk: 'Область розрахунку',
                          ),
                        ),
                        items: PricingRunScopeChoice.values
                            .map(
                              (choice) => DropdownMenuItem(
                                value: choice,
                                child: Text(
                                  choice.label(context),
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                            )
                            .toList(growable: false),
                        onChanged: _mutating
                            ? null
                            : (value) => setState(
                                () => _scope =
                                    value ?? PricingRunScopeChoice.fullCatalog,
                              ),
                      );
                  final actions = Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      FilledButton.icon(
                        key: const ValueKey('pricing-run-start'),
                        onPressed:
                            _selectedBatchId == null ||
                                _mutating ||
                                _hasActiveRun ||
                                sessionExpired
                            ? null
                            : _start,
                        icon: _mutating
                            ? const SizedBox.square(
                                dimension: 16,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : const Icon(Icons.play_arrow_rounded),
                        label: Text(
                          context.localized(ru: 'Запустить', uk: 'Запустити'),
                        ),
                      ),
                      if (_hasActiveRun)
                        OutlinedButton.icon(
                          key: const ValueKey('pricing-run-cancel'),
                          onPressed:
                              _mutating ||
                                  !_active!.isCancellable ||
                                  sessionExpired
                              ? null
                              : _cancel,
                          icon: const Icon(Icons.stop_circle_outlined),
                          label: Text(
                            _active!.isStopping
                                ? context.localized(
                                    ru: 'Останавливается',
                                    uk: 'Зупиняється',
                                  )
                                : context.localized(
                                    ru: 'Отменить',
                                    uk: 'Скасувати',
                                  ),
                          ),
                        ),
                    ],
                  );
                  if (constraints.maxWidth < 620) {
                    return Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        selector,
                        const SizedBox(height: 10),
                        scopeSelector,
                        const SizedBox(height: 10),
                        actions,
                      ],
                    );
                  }
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Row(
                        children: [
                          Expanded(child: selector),
                          const SizedBox(width: 12),
                          Expanded(child: scopeSelector),
                        ],
                      ),
                      const SizedBox(height: 10),
                      Align(
                        alignment: AlignmentDirectional.centerStart,
                        child: actions,
                      ),
                    ],
                  );
                },
              ),
              if (_imports.isEmpty) ...[
                const SizedBox(height: 8),
                Text(
                  context.localized(
                    ru: 'Сначала импортируйте завершённый или частичный каталог.',
                    uk: 'Спочатку імпортуйте завершений або частковий каталог.',
                  ),
                  style: Theme.of(
                    context,
                  ).textTheme.bodySmall?.copyWith(color: colors.muted),
                ),
              ],
            ] else ...[
              const SizedBox(height: 10),
              Text(
                context.localized(
                  ru: 'Запуск и отмена доступны администратору; статус виден всем участникам.',
                  uk: 'Запуск і скасування доступні адміністратору; статус бачать усі учасники.',
                ),
                style: Theme.of(
                  context,
                ).textTheme.bodySmall?.copyWith(color: colors.muted),
              ),
            ],
          ],
        ],
      ),
    );
  }
}

class _RunStatus extends StatelessWidget {
  const _RunStatus({required this.run, this.importName});

  final PricingRunSummary run;
  final String? importName;

  @override
  Widget build(BuildContext context) {
    final progress = run.progress;
    final status = _runStatusLabel(context, run.status);
    final processed = run.completedItems + run.failedItems;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Wrap(
          spacing: 8,
          runSpacing: 6,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Icon(_runStatusIcon(run.status), size: 20),
            Text(status, style: Theme.of(context).textTheme.titleSmall),
            // Say what the number counts. It only moves once items reach the
            // calculation stage, so a bare "0/8" during collection reads as a
            // stalled run rather than as "nothing calculated yet".
            if (run.totalItems > 0)
              Text(
                context.localized(
                  ru: 'рассчитано $processed из ${run.totalItems}',
                  uk: 'розраховано $processed з ${run.totalItems}',
                ),
                style: Theme.of(context).textTheme.bodySmall,
              ),
          ],
        ),
        if (importName case final name?) ...[
          const SizedBox(height: 6),
          Text(
            context.localized(ru: 'Импорт: $name', uk: 'Імпорт: $name'),
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
        if (!run.isFinished || progress != null) ...[
          const SizedBox(height: 8),
          LinearProgressIndicator(value: progress),
        ],
        if (run.isStopping) ...[
          const SizedBox(height: 8),
          MarkoInlineMessage(
            message: context.localized(
              ru: 'Отмена запрошена. Расчёт остановится после текущей позиции; уже сохранённые результаты останутся доступны.',
              uk: 'Скасування запитано. Розрахунок зупиниться після поточної позиції; вже збережені результати залишаться доступними.',
            ),
            tone: MarkoMessageTone.warning,
          ),
        ],
        if (run.manualReviewItems > 0) ...[
          const SizedBox(height: 7),
          Text(
            context.localized(
              ru: 'Требуют проверки: ${run.manualReviewItems}',
              uk: 'Потребують перевірки: ${run.manualReviewItems}',
            ),
          ),
        ],
        if (run.correlationId case final correlationId?) ...[
          const SizedBox(height: 7),
          // Support still needs this string; the operator needs to know what it
          // is for rather than seeing a raw engineering identifier.
          SelectableText(
            context.localized(
              ru: 'Номер расчёта для поддержки: $correlationId',
              uk: 'Номер розрахунку для підтримки: $correlationId',
            ),
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
        if (run.error != null && run.error!.trim().isNotEmpty) ...[
          const SizedBox(height: 8),
          MarkoInlineMessage(
            message: context.localized(
              ru: 'Причина сбоя: ${run.error}',
              uk: 'Причина збою: ${run.error}',
            ),
            tone: MarkoMessageTone.error,
          ),
        ],
      ],
    );
  }
}

/// Every status the backend can persist has to say something a shop owner can
/// act on. `queued`, `collecting`, `classifying`, `calibrating` and
/// `calculating` used to fall through to "Неизвестное состояние: collecting",
/// which covers most of a run's visible lifetime.
String _runStatusLabel(BuildContext context, String status) => switch (status) {
  'pending' ||
  'queued' => context.localized(ru: 'Ожидает запуска', uk: 'Очікує запуску'),
  'collecting' => context.localized(
    ru: 'Ищем предложения конкурентов',
    uk: 'Шукаємо пропозиції конкурентів',
  ),
  'classifying' => context.localized(
    ru: 'Разбираем найденные предложения',
    uk: 'Розбираємо знайдені пропозиції',
  ),
  'calibrating' => context.localized(
    ru: 'Готовим расчёт',
    uk: 'Готуємо розрахунок',
  ),
  'calculating' => context.localized(
    ru: 'Считаем рекомендации',
    uk: 'Рахуємо рекомендації',
  ),
  'running' => context.localized(
    ru: 'Расчёт выполняется',
    uk: 'Розрахунок виконується',
  ),
  'completed' => context.localized(
    ru: 'Расчёт завершён',
    uk: 'Розрахунок завершено',
  ),
  'partial' => context.localized(
    ru: 'Завершён частично',
    uk: 'Завершено частково',
  ),
  'cancelled' => context.localized(
    ru: 'Расчёт отменён',
    uk: 'Розрахунок скасовано',
  ),
  'failed' => context.localized(
    ru: 'Расчёт завершился с ошибкой',
    uk: 'Розрахунок завершився з помилкою',
  ),
  _ => context.localized(
    ru: 'Неизвестное состояние: $status',
    uk: 'Невідомий стан: $status',
  ),
};

IconData _runStatusIcon(String status) => switch (status) {
  'completed' => Icons.check_circle_outline_rounded,
  'partial' => Icons.warning_amber_rounded,
  'cancelled' => Icons.cancel_outlined,
  'failed' => Icons.error_outline_rounded,
  'running' ||
  'collecting' ||
  'classifying' ||
  'calibrating' ||
  'calculating' => Icons.sync_rounded,
  _ => Icons.schedule_rounded,
};
