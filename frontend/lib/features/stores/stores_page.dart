import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/app_language.dart';
import '../../core/app_theme.dart';
import '../../core/marko_motion.dart';
import '../../core/marko_ui.dart';
import '../../core/presentation_formatters.dart';
import '../../core/widgets/marko_skeleton.dart';
import '../../core/widgets/marko_button.dart';
import '../attention/attention_controller.dart';
import '../catalog/catalog_controller.dart';
import 'store_models.dart';
import 'stores_controller.dart';

class StoresPage extends ConsumerStatefulWidget {
  const StoresPage({
    this.ownedOnly = false,
    this.canAdministerWorkspace = false,
    this.onOpenStoreCatalog,
    this.onImportCatalog,
    super.key,
  });

  final bool ownedOnly;
  final bool canAdministerWorkspace;

  /// Opens a store inside the dashboard's catalog tab with that store already
  /// selected. Without it the row falls back to the standalone catalog route.
  final void Function(String storeId)? onOpenStoreCatalog;
  final VoidCallback? onImportCatalog;

  @override
  ConsumerState<StoresPage> createState() => _StoresPageState();
}

class _StoresPageState extends ConsumerState<StoresPage> {
  final _urlController = TextEditingController();

  void _openStore(StoreSummary store) {
    final openInCatalogTab = widget.onOpenStoreCatalog;
    if (openInCatalogTab != null) {
      openInCatalogTab(store.id);
      return;
    }
    context.pushNamed('store-products', pathParameters: {'storeId': store.id});
  }

  Future<void> _confirmDeleteStore(
    StoresController controller,
    StoreSummary store,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(
          dialogContext.localized(
            ru: 'Удалить магазин?',
            uk: 'Видалити магазин?',
          ),
        ),
        content: Text(
          dialogContext.localized(
            ru:
                'Магазин «${store.displayName}» и его каталог исчезнут из '
                'раздела «Мои магазины». Данные на Prom.ua не изменятся.',
            uk:
                'Магазин «${store.displayName}» і його каталог зникнуть із '
                'розділу «Мої магазини». Дані на Prom.ua не зміняться.',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: Text(dialogContext.localized(ru: 'Отмена', uk: 'Скасувати')),
          ),
          TextButton(
            key: const ValueKey('confirm-delete-store'),
            onPressed: () => Navigator.of(dialogContext).pop(true),
            style: TextButton.styleFrom(
              foregroundColor: MarkoTheme.of(dialogContext).negative,
            ),
            child: Text(dialogContext.localized(ru: 'Удалить', uk: 'Видалити')),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    final deleted = await controller.deleteStore(store);
    if (!deleted || !mounted) return;
    // Dashboard tabs stay mounted in an IndexedStack. Explicitly reload their
    // read models so deleted-store products disappear without a page refresh.
    ref.invalidate(catalogControllerProvider);
    ref.invalidate(attentionControllerProvider);
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Text(
            context.localized(
              ru: 'Магазин «${store.displayName}» удалён',
              uk: 'Магазин «${store.displayName}» видалено',
            ),
          ),
        ),
      );
  }

  @override
  void dispose() {
    _urlController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final asyncState = ref.watch(storesControllerProvider);
    final controller = ref.read(storesControllerProvider.notifier);

    return GestureDetector(
      onTap: () => FocusManager.instance.primaryFocus?.unfocus(),
      child: asyncState.when(
        loading: () => const MarkoQueueSkeleton(),
        error: (error, _) => MarkoAsyncErrorView(
          error: error,
          forbiddenResourceRu: 'разделу магазинов',
          forbiddenResourceUk: 'розділу магазинів',
          onRetry: controller.refresh,
        ),
        data: (state) {
          final availableStores = widget.ownedOnly
              ? state.stores
                    .where((store) => store.kind == 'owned')
                    .toList(growable: false)
              : state.stores;
          return RefreshIndicator(
            onRefresh: controller.refresh,
            child: ListView(
              padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 28),
              children: [
                Center(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 1120),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        _PageHeading(
                          ownedOnly: widget.ownedOnly,
                          onImportCatalog: widget.onImportCatalog,
                        ),
                        const SizedBox(height: 24),
                        if (widget.canAdministerWorkspace)
                          _AddStorePanel(
                            urlController: _urlController,
                            busy: state.isSubmitting || state.isDeleting,
                            onSubmit: () async {
                              final accepted = await controller.addStore(
                                _urlController.text,
                              );
                              if (accepted && mounted) _urlController.clear();
                            },
                          )
                        else
                          MarkoInlineMessage(
                            message: context.localized(
                              ru: 'Подключение, синхронизация и удаление магазинов доступны владельцу или администратору.',
                              uk: 'Підключення, синхронізація та видалення магазинів доступні власнику або адміністратору.',
                            ),
                            tone: MarkoMessageTone.info,
                          ),
                        if (state.activeSync != null) ...[
                          const SizedBox(height: 14),
                          _SyncPanel(
                            sync: state.activeSync!,
                            job: state.activeJob,
                          ),
                        ],
                        if (state.error != null) ...[
                          const SizedBox(height: 14),
                          MarkoInlineMessage(
                            message: state.error!,
                            tone: MarkoMessageTone.error,
                            action: TextButton(
                              onPressed:
                                  state.activeJob?.status == 'monitoring_failed'
                                  ? controller.retryMonitoring
                                  : controller.dismissError,
                              child: Text(
                                state.activeJob?.status == 'monitoring_failed'
                                    ? context.localized(
                                        ru: 'Повторить отслеживание',
                                        uk: 'Повторити відстеження',
                                      )
                                    : context.localized(
                                        ru: 'Закрыть',
                                        uk: 'Закрити',
                                      ),
                              ),
                            ),
                          ),
                        ],
                        const SizedBox(height: 30),
                        _StoresHeading(
                          count: availableStores.length,
                          onRefresh: controller.refresh,
                        ),
                        const SizedBox(height: 12),
                        if (availableStores.isEmpty)
                          const _EmptyStores()
                        else
                          MarkoPanel(
                            padding: EdgeInsets.zero,
                            child: Column(
                              children: [
                                for (
                                  var index = 0;
                                  index < availableStores.length;
                                  index++
                                ) ...[
                                  _StoreRow(
                                    store: availableStores[index],
                                    syncDisabled:
                                        !widget.canAdministerWorkspace ||
                                        state.isSubmitting ||
                                        state.hasActiveJob ||
                                        state.isDeleting,
                                    deleting:
                                        state.deletingStoreId ==
                                        availableStores[index].id,
                                    deleteDisabled:
                                        state.isSubmitting || state.isDeleting,
                                    onOpen: () =>
                                        _openStore(availableStores[index]),
                                    onSync: () => controller.syncStore(
                                      availableStores[index],
                                    ),
                                    onDelete:
                                        widget.ownedOnly &&
                                            widget.canAdministerWorkspace
                                        ? () => _confirmDeleteStore(
                                            controller,
                                            availableStores[index],
                                          )
                                        : null,
                                  ),
                                  if (index < availableStores.length - 1)
                                    const Divider(),
                                ],
                              ],
                            ),
                          ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _PageHeading extends StatelessWidget {
  const _PageHeading({required this.ownedOnly, required this.onImportCatalog});

  final bool ownedOnly;
  final VoidCallback? onImportCatalog;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return MarkoFadeUp(
      child: Wrap(
        alignment: WrapAlignment.spaceBetween,
        crossAxisAlignment: WrapCrossAlignment.center,
        spacing: 18,
        runSpacing: 12,
        children: [
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  ownedOnly
                      ? context.localized(ru: 'Источники', uk: 'Джерела')
                      : context.localized(
                          ru: 'Магазины Prom',
                          uk: 'Магазини Prom',
                        ),
                  style: Theme.of(context).textTheme.headlineMedium,
                ),
                const SizedBox(height: 7),
                Text(
                  ownedOnly
                      ? context.localized(
                          ru: 'Подключите магазин Prom или загрузите XLSX — товары появятся в каталоге, а проверку цен вы запускаете сами.',
                          uk: 'Підключіть магазин Prom або завантажте XLSX — товари з’являться в каталозі, а перевірку цін ви запускаєте самі.',
                        )
                      : context.localized(
                          ru: 'Подключайте каталоги и управляйте их синхронизацией.',
                          uk: 'Підключайте каталоги та керуйте їх синхронізацією.',
                        ),
                  style: Theme.of(
                    context,
                  ).textTheme.bodyMedium?.copyWith(color: colors.muted),
                ),
              ],
            ),
          ),
          if (onImportCatalog != null)
            OutlinedButton.icon(
              onPressed: onImportCatalog,
              icon: const Icon(Icons.upload_file_outlined),
              label: Text(
                context.localized(ru: 'Загрузить XLSX', uk: 'Завантажити XLSX'),
              ),
            ),
        ],
      ),
    );
  }
}

class _AddStorePanel extends StatelessWidget {
  const _AddStorePanel({
    required this.urlController,
    required this.busy,
    required this.onSubmit,
  });

  final TextEditingController urlController;
  final bool busy;
  final VoidCallback onSubmit;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return MarkoPanel(
      padding: const EdgeInsets.all(22),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 36,
                height: 36,
                decoration: BoxDecoration(
                  color: colors.brandSoft,
                  borderRadius: BorderRadius.circular(9),
                ),
                alignment: Alignment.center,
                child: Icon(
                  Icons.add_business_outlined,
                  size: 19,
                  color: colors.brand,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      context.localized(
                        ru: 'Подключить магазин',
                        uk: 'Підключити магазин',
                      ),
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 2),
                    Text(
                      context.localized(
                        ru: 'Вставьте публичную ссылку на магазин prom.ua.',
                        uk: 'Вставте публічне посилання на магазин prom.ua.',
                      ),
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 18),
          LayoutBuilder(
            builder: (context, constraints) {
              final field = TextField(
                controller: urlController,
                enabled: !busy,
                keyboardType: TextInputType.url,
                decoration: InputDecoration(
                  labelText: context.localized(
                    ru: 'Ссылка на магазин',
                    uk: 'Посилання на магазин',
                  ),
                  hintText: 'https://prom.ua/ua/c2847093-kemp.html',
                  prefixIcon: const Icon(Icons.link_rounded, size: 20),
                ),
                onSubmitted: (_) => busy ? null : onSubmit(),
              );
              final button = MarkoButton(
                label: context.localized(ru: 'Подключить', uk: 'Підключити'),
                onPressed: busy ? null : onSubmit,
                icon: Icons.add_rounded,
                loading: busy,
                expand: constraints.maxWidth < 650,
              );
              if (constraints.maxWidth < 650) {
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [field, const SizedBox(height: 12), button],
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  Expanded(child: field),
                  const SizedBox(width: 12),
                  button,
                ],
              );
            },
          ),
        ],
      ),
    );
  }
}

class _SyncPanel extends StatelessWidget {
  const _SyncPanel({required this.sync, required this.job});

  final StoreSync sync;
  final SyncRun? job;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final status = job?.status ?? sync.status;
    final failed = status == 'failed' || status == 'monitoring_failed';
    final completed = status == 'completed';
    final foreground = failed
        ? colors.negative
        : completed
        ? colors.positive
        : colors.brand;
    final background = failed
        ? colors.negativeSoft
        : completed
        ? colors.positiveSoft
        : colors.brandSoft;

    return MarkoPanel(
      color: background,
      borderColor: background,
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                failed
                    ? Icons.error_outline_rounded
                    : completed
                    ? Icons.check_circle_outline_rounded
                    : Icons.sync_rounded,
                size: 19,
                color: foreground,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  '${context.localized(ru: 'Импорт каталога', uk: 'Імпорт каталогу')}: '
                  '${_syncStatusLabel(context, job?.status ?? status)}',
                  style: Theme.of(
                    context,
                  ).textTheme.titleMedium?.copyWith(color: foreground),
                ),
              ),
              Text(
                context.localized(
                  ru: '${job?.progressCurrent ?? 0} товаров',
                  uk: '${job?.progressCurrent ?? 0} товарів',
                ),
                style: Theme.of(
                  context,
                ).textTheme.labelMedium?.copyWith(color: foreground),
              ),
            ],
          ),
          const SizedBox(height: 12),
          LinearProgressIndicator(
            value: job?.progress,
            color: foreground,
            backgroundColor: colors.surface.withValues(alpha: 0.7),
          ),
          if (job != null) ...[
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                _SyncMetricChip(
                  label: context.localized(
                    ru: 'Страницы: ${job!.catalogPages}',
                    uk: 'Сторінки: ${job!.catalogPages}',
                  ),
                  foreground: foreground,
                ),
                _SyncMetricChip(
                  label: context.localized(
                    ru: 'Извлечено: ${job!.productsExtracted}',
                    uk: 'Вилучено: ${job!.productsExtracted}',
                  ),
                  foreground: foreground,
                ),
                _SyncMetricChip(
                  label: context.localized(
                    ru: 'Сохранено: ${job!.productsPersisted}',
                    uk: 'Збережено: ${job!.productsPersisted}',
                  ),
                  foreground: foreground,
                ),
                _SyncMetricChip(
                  label: context.localized(
                    ru: 'Дубликаты: ${job!.duplicateProducts}',
                    uk: 'Дублікати: ${job!.duplicateProducts}',
                  ),
                  foreground: foreground,
                ),
                _SyncMetricChip(
                  label: context.localized(
                    ru: 'Записи в БД: ${job!.databaseWrites}',
                    uk: 'Записи в БД: ${job!.databaseWrites}',
                  ),
                  foreground: foreground,
                ),
                if (job!.maxTaskExecutions > 0 || job!.taskExecutions > 0)
                  _SyncMetricChip(
                    label: context.localized(
                      ru: 'Запуски задачи: ${job!.taskExecutions}/${job!.maxTaskExecutions}',
                      uk: 'Запуски завдання: ${job!.taskExecutions}/${job!.maxTaskExecutions}',
                    ),
                    foreground: foreground,
                  ),
                if (job!.taskRedeliveries > 0)
                  _SyncMetricChip(
                    label: context.localized(
                      ru: 'Повторные доставки: ${job!.taskRedeliveries}',
                      uk: 'Повторні доставки: ${job!.taskRedeliveries}',
                    ),
                    foreground: foreground,
                  ),
                if (job!.deduplicatedSubmissions > 0)
                  _SyncMetricChip(
                    label: context.localized(
                      ru: 'Дедуплицировано запусков: ${job!.deduplicatedSubmissions}',
                      uk: 'Дедупліковано запусків: ${job!.deduplicatedSubmissions}',
                    ),
                    foreground: foreground,
                  ),
                if (job!.rawEvidenceBytes > 0)
                  _SyncMetricChip(
                    label: context.localized(
                      ru: 'Raw evidence: ${_formatByteCount(job!.rawEvidenceBytes)}',
                      uk: 'Raw evidence: ${_formatByteCount(job!.rawEvidenceBytes)}',
                    ),
                    foreground: foreground,
                  ),
                if (job!.structuredCompleteness != null)
                  _SyncMetricChip(
                    label: context.localized(
                      ru: 'Полнота структуры: ${_formatPercent(job!.structuredCompleteness!)}',
                      uk: 'Повнота структури: ${_formatPercent(job!.structuredCompleteness!)}',
                    ),
                    foreground: foreground,
                  ),
                if (job!.evidenceCoverage != null)
                  _SyncMetricChip(
                    label: context.localized(
                      ru: 'Покрытие доказательств: ${_formatPercent(job!.evidenceCoverage!)}',
                      uk: 'Покриття доказів: ${_formatPercent(job!.evidenceCoverage!)}',
                    ),
                    foreground: foreground,
                  ),
                if (job!.deadlineAt != null)
                  _SyncMetricChip(
                    label: context.localized(
                      ru: 'Дедлайн: ${formatLocalDateTime(job!.deadlineAt!)}',
                      uk: 'Дедлайн: ${formatLocalDateTime(job!.deadlineAt!)}',
                    ),
                    foreground: foreground,
                  ),
                if (job!.leaseExpiresAt != null)
                  _SyncMetricChip(
                    label: context.localized(
                      ru: 'Lease до: ${formatLocalDateTime(job!.leaseExpiresAt!)}',
                      uk: 'Lease до: ${formatLocalDateTime(job!.leaseExpiresAt!)}',
                    ),
                    foreground: foreground,
                  ),
              ],
            ),
          ],
          if (job?.error != null) ...[
            const SizedBox(height: 10),
            Text(
              job!.error!,
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: foreground),
            ),
          ],
        ],
      ),
    );
  }
}

class _SyncMetricChip extends StatelessWidget {
  const _SyncMetricChip({required this.label, required this.foreground});

  final String label;
  final Color foreground;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
      decoration: BoxDecoration(
        color: MarkoTheme.of(context).surface.withValues(alpha: 0.72),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        label,
        style: Theme.of(
          context,
        ).textTheme.labelSmall?.copyWith(color: foreground),
      ),
    );
  }
}

String _formatPercent(double ratio) => '${(ratio * 100).toStringAsFixed(1)}%';

String _formatByteCount(int bytes) {
  if (bytes < 1024) return '$bytes B';
  if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
  return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
}

class _StoresHeading extends StatelessWidget {
  const _StoresHeading({required this.count, required this.onRefresh});

  final int count;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Row(
      children: [
        Expanded(
          child: Text(
            context.localized(ru: 'Подключённые', uk: 'Підключені'),
            style: Theme.of(context).textTheme.titleLarge,
          ),
        ),
        const SizedBox(width: 9),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
          decoration: BoxDecoration(
            color: colors.surfaceMuted,
            borderRadius: BorderRadius.circular(6),
          ),
          child: Text(
            count.toString(),
            style: Theme.of(context).textTheme.labelMedium,
          ),
        ),
        const SizedBox(width: 8),
        IconButton(
          tooltip: context.localized(
            ru: 'Обновить список',
            uk: 'Оновити список',
          ),
          onPressed: onRefresh,
          icon: const Icon(Icons.refresh_rounded, size: 19),
        ),
      ],
    );
  }
}

class _StoreRow extends StatelessWidget {
  const _StoreRow({
    required this.store,
    required this.syncDisabled,
    required this.deleting,
    required this.deleteDisabled,
    required this.onOpen,
    required this.onSync,
    required this.onDelete,
  });

  final StoreSummary store;
  final bool syncDisabled;
  final bool deleting;
  final bool deleteDisabled;
  final VoidCallback onOpen;
  final VoidCallback onSync;
  final VoidCallback? onDelete;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onOpen,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
          child: LayoutBuilder(
            builder: (context, constraints) {
              final compact = constraints.maxWidth < 560;
              final description = compact
                  ? '${_storeSyncDescription(context, store)} · '
                        '${_productCountLabel(context, store.productCount)}'
                  : _storeSyncDescription(context, store);
              return Row(
                children: [
                  Container(
                    width: 40,
                    height: 40,
                    decoration: BoxDecoration(
                      color: colors.surfaceMuted,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    alignment: Alignment.center,
                    child: Icon(
                      Icons.storefront_outlined,
                      size: 20,
                      color: colors.ink,
                    ),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          store.displayName,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                        const SizedBox(height: 3),
                        Text(
                          description,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ],
                    ),
                  ),
                  if (!compact) ...[
                    const SizedBox(width: 12),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 9,
                        vertical: 5,
                      ),
                      decoration: BoxDecoration(
                        color: colors.surfaceMuted,
                        borderRadius: BorderRadius.circular(7),
                      ),
                      child: Text(
                        _productCountLabel(context, store.productCount),
                        style: Theme.of(
                          context,
                        ).textTheme.labelMedium?.copyWith(color: colors.ink),
                      ),
                    ),
                    const SizedBox(width: 8),
                  ],
                  IconButton(
                    tooltip: context.localized(
                      ru: 'Синхронизировать',
                      uk: 'Синхронізувати',
                    ),
                    onPressed: syncDisabled ? null : onSync,
                    icon: const Icon(Icons.sync_rounded, size: 19),
                  ),
                  if (onDelete != null)
                    IconButton(
                      key: ValueKey('delete-store-${store.id}'),
                      tooltip: context.localized(
                        ru: 'Удалить магазин',
                        uk: 'Видалити магазин',
                      ),
                      onPressed: deleteDisabled ? null : onDelete,
                      icon: deleting
                          ? SizedBox.square(
                              dimension: 18,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                color: colors.negative,
                              ),
                            )
                          : Icon(
                              Icons.delete_outline_rounded,
                              size: 19,
                              color: deleteDisabled
                                  ? colors.muted
                                  : colors.negative,
                            ),
                    ),
                  if (!compact)
                    Icon(
                      Icons.chevron_right_rounded,
                      color: colors.muted,
                      size: 20,
                    ),
                ],
              );
            },
          ),
        ),
      ),
    );
  }
}

class _EmptyStores extends StatelessWidget {
  const _EmptyStores();

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return MarkoPanel(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 34),
      child: Column(
        children: [
          Icon(Icons.storefront_outlined, color: colors.muted, size: 28),
          const SizedBox(height: 12),
          Text(
            context.localized(
              ru: 'Магазинов пока нет',
              uk: 'Магазинів поки немає',
            ),
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 5),
          Text(
            context.localized(
              ru: 'Добавьте первый магазин по ссылке выше.',
              uk: 'Додайте перший магазин за посиланням вище.',
            ),
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

String _storeSyncDescription(BuildContext context, StoreSummary store) {
  final value = store.lastSyncedAt;
  if (value == null) {
    return context.localized(
      ru: 'ещё не синхронизирован',
      uk: 'ще не синхронізовано',
    );
  }
  final formatted = formatLocalDateTime(value);
  return context.localized(
    ru: 'обновлён $formatted',
    uk: 'оновлено $formatted',
  );
}

String _syncStatusLabel(BuildContext context, String status) {
  return switch (status) {
    'queued' => context.localized(ru: 'в очереди', uk: 'у черзі'),
    'running' => context.localized(ru: 'выполняется', uk: 'виконується'),
    'completed' => context.localized(ru: 'готово', uk: 'готово'),
    'failed' => context.localized(ru: 'ошибка', uk: 'помилка'),
    _ => status,
  };
}

String _productCountLabel(BuildContext context, int count) {
  return context.localized(ru: '$count товаров', uk: '$count товарів');
}
