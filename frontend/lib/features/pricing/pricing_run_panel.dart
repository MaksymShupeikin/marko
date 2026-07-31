import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/app_language.dart';
import '../../core/app_theme.dart';
import '../../core/marko_ui.dart';
import '../catalog/catalog_import_api.dart';
import '../catalog/catalog_import_models.dart';
import 'pricing_api.dart';
import 'pricing_models.dart';

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
  bool _mutating = false;
  String? _error;
  String? _selectedBatchId;
  List<CatalogImportBatch> _imports = const [];
  List<PricingRunSummary> _runs = const [];
  PricingRunSummary? _active;

  PricingApi get _pricing => ref.read(pricingApiProvider);
  CatalogImportApi get _catalog => ref.read(catalogImportApiProvider);

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
      final runsFuture = _pricing.listRuns();
      final importsFuture = _catalog.list();
      final runs = await runsFuture;
      final imports = await importsFuture;
      if (!mounted) return;
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
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = error.toString();
      });
    }
  }

  Future<void> _start() async {
    final batchId = _selectedBatchId;
    if (batchId == null || _mutating) return;
    final confirmed = await _confirm(
      titleRu: 'Запустить расчёт цен?',
      titleUk: 'Запустити розрахунок цін?',
      bodyRu:
          'Расчёт использует выбранный импорт и не меняет цены на Prom.ua автоматически.',
      bodyUk:
          'Розрахунок використовує вибраний імпорт і не змінює ціни на Prom.ua автоматично.',
      actionRu: 'Запустить',
      actionUk: 'Запустити',
    );
    if (!confirmed || !mounted) return;
    setState(() {
      _mutating = true;
      _error = null;
    });
    try {
      final run = await _pricing.startRun(batchId);
      if (!mounted) return;
      setState(() {
        _active = run;
        _runs = [run, ..._runs.where((item) => item.id != run.id)];
      });
      await _poll(run);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _mutating = false);
    }
  }

  Future<void> _poll(PricingRunSummary run) async {
    try {
      final finished = await pollPricingRun(
        fetch: _pricing.getRun,
        runId: run.id,
        onUpdate: (updated) {
          if (!mounted) return;
          setState(() {
            _active = updated;
            _runs = [updated, ..._runs.where((item) => item.id != updated.id)];
          });
        },
      );
      if (finished.isFinished) widget.onRunFinished();
    } on PricingRunPollingLimitExceeded catch (error) {
      if (!mounted) return;
      setState(() {
        _error = context.localized(
          ru: 'Автообновление остановлено после ${error.attempts} попыток. Расчёт не отменён — нажмите «Обновить статус».',
          uk: 'Автооновлення зупинено після ${error.attempts} спроб. Розрахунок не скасовано — натисніть «Оновити статус».',
        );
      });
    }
  }

  Future<void> _cancel() async {
    final run = _active;
    if (run == null || run.isFinished || _mutating) return;
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
    try {
      final updated = await _pricing.cancelRun(run.id);
      if (!mounted) return;
      setState(() => _active = updated);
      if (!updated.isFinished) await _poll(updated);
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _mutating = false);
    }
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
                onPressed: _loading || _mutating ? null : _load,
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
              _RunStatus(run: _active!),
            if (_error != null) ...[
              const SizedBox(height: 12),
              MarkoInlineMessage(
                message: _error!,
                tone: MarkoMessageTone.error,
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
                  final actions = Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      FilledButton.icon(
                        key: const ValueKey('pricing-run-start'),
                        onPressed: _selectedBatchId == null || _mutating
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
                      if (_active != null && !_active!.isFinished)
                        OutlinedButton.icon(
                          key: const ValueKey('pricing-run-cancel'),
                          onPressed: _mutating ? null : _cancel,
                          icon: const Icon(Icons.stop_circle_outlined),
                          label: Text(
                            context.localized(ru: 'Отменить', uk: 'Скасувати'),
                          ),
                        ),
                    ],
                  );
                  if (constraints.maxWidth < 620) {
                    return Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [selector, const SizedBox(height: 10), actions],
                    );
                  }
                  return Row(
                    children: [
                      Expanded(child: selector),
                      const SizedBox(width: 12),
                      actions,
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
  const _RunStatus({required this.run});

  final PricingRunSummary run;

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
            if (run.totalItems > 0)
              Text(
                '$processed/${run.totalItems}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
          ],
        ),
        if (!run.isFinished || progress != null) ...[
          const SizedBox(height: 8),
          LinearProgressIndicator(value: progress),
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
          SelectableText(
            'Correlation ID: $correlationId',
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

String _runStatusLabel(BuildContext context, String status) => switch (status) {
  'pending' => context.localized(ru: 'Ожидает запуска', uk: 'Очікує запуску'),
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
  'running' => Icons.sync_rounded,
  _ => Icons.schedule_rounded,
};
