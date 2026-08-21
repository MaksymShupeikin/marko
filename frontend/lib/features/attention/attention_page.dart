import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/app_language.dart';
import '../../core/app_theme.dart';
import '../../core/marko_motion.dart';
import '../../core/marko_ui.dart';
import '../../core/presentation_formatters.dart';
import '../../core/widgets/marko_skeleton.dart';
import 'attention_controller.dart';
import 'attention_models.dart';

class AttentionPage extends ConsumerStatefulWidget {
  const AttentionPage({
    required this.onOpenSources,
    this.onOpenRecommendation,
    super.key,
  });

  final VoidCallback onOpenSources;
  final ValueChanged<String>? onOpenRecommendation;

  @override
  ConsumerState<AttentionPage> createState() => _AttentionPageState();
}

class _AttentionPageState extends ConsumerState<AttentionPage> {
  final _searchController = TextEditingController();
  Timer? _searchTimer;

  @override
  void dispose() {
    _searchTimer?.cancel();
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final asyncState = ref.watch(attentionControllerProvider);
    final controller = ref.read(attentionControllerProvider.notifier);
    return asyncState.when(
      loading: () => const MarkoQueueSkeleton(),
      error: (error, _) => SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: MarkoAsyncErrorView(
          error: error,
          forbiddenResourceRu: 'очереди внимания',
          forbiddenResourceUk: 'черги уваги',
          onRetry: () => ref.invalidate(attentionControllerProvider),
        ),
      ),
      data: (state) => RefreshIndicator(
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
                    _Header(
                      summary: state.summary,
                      refreshing: state.isRefreshing,
                      onRefresh: controller.refresh,
                    ),
                    const SizedBox(height: 22),
                    _SummaryCards(
                      summary: state.summary,
                      selected: state.status,
                      onSelected: controller.selectStatus,
                    ),
                    const SizedBox(height: 18),
                    TextField(
                      key: const ValueKey('attention-search'),
                      controller: _searchController,
                      textInputAction: TextInputAction.search,
                      onChanged: (value) {
                        _searchTimer?.cancel();
                        _searchTimer = Timer(
                          const Duration(milliseconds: 350),
                          () => controller.search(value),
                        );
                      },
                      onSubmitted: controller.search,
                      decoration: InputDecoration(
                        hintText: context.localized(
                          ru: 'Поиск по товару, SKU или OEM',
                          uk: 'Пошук за товаром, SKU або OEM',
                        ),
                        prefixIcon: const Icon(Icons.search_rounded),
                        suffixIcon: _searchController.text.isEmpty
                            ? null
                            : IconButton(
                                tooltip: context.localized(
                                  ru: 'Очистить',
                                  uk: 'Очистити',
                                ),
                                onPressed: () {
                                  setState(_searchController.clear);
                                  unawaited(controller.search(''));
                                },
                                icon: const Icon(Icons.close_rounded),
                              ),
                      ),
                    ),
                    if (state.isRefreshing) ...[
                      const SizedBox(height: 2),
                      const LinearProgressIndicator(minHeight: 2),
                    ],
                    if (state.error != null) ...[
                      const SizedBox(height: 12),
                      MarkoInlineMessage(
                        message: state.error!,
                        tone: MarkoMessageTone.error,
                      ),
                    ],
                    const SizedBox(height: 18),
                    if (state.page.items.isEmpty)
                      _EmptyState(
                        filtered:
                            state.status != null || state.query.isNotEmpty,
                        onOpenSources: widget.onOpenSources,
                        onClear: () {
                          _searchController.clear();
                          unawaited(controller.selectStatus(null));
                          unawaited(controller.search(''));
                        },
                      )
                    else
                      ...state.page.items.map(
                        (item) => Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: _AttentionCard(
                            item: item,
                            onOpen:
                                item.recommendationId == null ||
                                    widget.onOpenRecommendation == null
                                ? null
                                : () => widget.onOpenRecommendation!(
                                    item.recommendationId!,
                                  ),
                          ),
                        ),
                      ),
                    if (state.page.hasMore) ...[
                      const SizedBox(height: 6),
                      Center(
                        child: OutlinedButton.icon(
                          onPressed: state.isLoadingMore
                              ? null
                              : controller.loadMore,
                          icon: state.isLoadingMore
                              ? const SizedBox.square(
                                  dimension: 16,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                  ),
                                )
                              : const Icon(Icons.expand_more_rounded),
                          label: Text(
                            context.localized(
                              ru: 'Показать ещё',
                              uk: 'Показати ще',
                            ),
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({
    required this.summary,
    required this.refreshing,
    required this.onRefresh,
  });

  final AttentionSummary summary;
  final bool refreshing;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final problemCount =
        summary.overpriced +
        summary.underpriced +
        summary.reviewRequired +
        summary.noData;
    return MarkoFadeUp(
      child: Wrap(
        alignment: WrapAlignment.spaceBetween,
        crossAxisAlignment: WrapCrossAlignment.center,
        spacing: 16,
        runSpacing: 12,
        children: [
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  problemCount == 0
                      ? context.localized(
                          ru: 'Цены под контролем',
                          uk: 'Ціни під контролем',
                        )
                      : _attentionTitle(context, problemCount),
                  style: Theme.of(context).textTheme.headlineMedium,
                ),
                const SizedBox(height: 7),
                Text(
                  _freshness(context, summary.updatedAt),
                  style: Theme.of(
                    context,
                  ).textTheme.bodyMedium?.copyWith(color: colors.muted),
                ),
              ],
            ),
          ),
          IconButton.outlined(
            tooltip: context.localized(ru: 'Обновить', uk: 'Оновити'),
            onPressed: refreshing ? null : onRefresh,
            icon: const Icon(Icons.refresh_rounded),
          ),
        ],
      ),
    );
  }
}

class _SummaryCards extends StatelessWidget {
  const _SummaryCards({
    required this.summary,
    required this.selected,
    required this.onSelected,
  });

  final AttentionSummary summary;
  final String? selected;
  final ValueChanged<String?> onSelected;

  @override
  Widget build(BuildContext context) {
    final entries = <_SummaryEntry>[
      _SummaryEntry(
        null,
        context.localized(ru: 'Все', uk: 'Усі'),
        summary.total,
      ),
      _SummaryEntry(
        'OVERPRICED',
        context.localized(ru: 'Дороже', uk: 'Дорожче'),
        summary.overpriced,
      ),
      _SummaryEntry(
        'UNDERPRICED',
        context.localized(ru: 'Дешевле', uk: 'Дешевше'),
        summary.underpriced,
      ),
      _SummaryEntry(
        'REVIEW_REQUIRED',
        context.localized(ru: 'Проверить', uk: 'Перевірити'),
        summary.reviewRequired,
      ),
      _SummaryEntry(
        'NO_DATA',
        context.localized(ru: 'Нет данных', uk: 'Немає даних'),
        summary.noData,
      ),
      _SummaryEntry(
        'IN_MARKET',
        context.localized(ru: 'В рынке', uk: 'У ринку'),
        summary.inMarket,
      ),
      _SummaryEntry(
        'PROCESSING',
        context.localized(ru: 'Считается', uk: 'Розраховується'),
        summary.processing,
      ),
    ];
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: entries
          .map(
            (entry) => ChoiceChip(
              selected: selected == entry.status,
              onSelected: (_) => onSelected(entry.status),
              label: Text('${entry.label} · ${entry.count}'),
            ),
          )
          .toList(growable: false),
    );
  }
}

class _SummaryEntry {
  const _SummaryEntry(this.status, this.label, this.count);

  final String? status;
  final String label;
  final int count;
}

class _AttentionCard extends StatelessWidget {
  const _AttentionCard({required this.item, required this.onOpen});

  final AttentionProduct item;
  final VoidCallback? onOpen;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final style = _statusStyle(context, colors, item.status);
    return MarkoPanel(
      padding: const EdgeInsets.all(16),
      interactive: true,
      onTap: onOpen,
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 700;
          final summary = _PriceSummary(item: item, color: style.foreground);
          final heading = Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 38,
                height: 38,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: style.background,
                  borderRadius: BorderRadius.circular(9),
                ),
                child: Icon(style.icon, size: 20, color: style.foreground),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      item.name,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      [
                        if (item.sku?.isNotEmpty ?? false) 'SKU ${item.sku}',
                        if (item.oe?.isNotEmpty ?? false) 'OEM ${item.oe}',
                        if (item.brand?.isNotEmpty ?? false) item.brand!,
                      ].join(' · '),
                      style: Theme.of(
                        context,
                      ).textTheme.bodySmall?.copyWith(color: colors.muted),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 10),
              _StatusBadge(style: style),
            ],
          );
          if (compact) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                heading,
                const SizedBox(height: 14),
                summary,
                if (onOpen != null) ...[
                  const SizedBox(height: 12),
                  OutlinedButton(
                    onPressed: onOpen,
                    child: Text(
                      context.localized(
                        ru: 'Открыть доказательства',
                        uk: 'Відкрити докази',
                      ),
                    ),
                  ),
                ],
              ],
            );
          }
          return Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Expanded(flex: 5, child: heading),
              const SizedBox(width: 22),
              Expanded(flex: 4, child: summary),
              if (onOpen != null) ...[
                const SizedBox(width: 16),
                IconButton.outlined(
                  tooltip: context.localized(
                    ru: 'Открыть доказательства',
                    uk: 'Відкрити докази',
                  ),
                  onPressed: onOpen,
                  icon: const Icon(Icons.arrow_forward_rounded),
                ),
              ],
            ],
          );
        },
      ),
    );
  }
}

class _PriceSummary extends StatelessWidget {
  const _PriceSummary({required this.item, required this.color});

  final AttentionProduct item;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '${_money(item.ourPrice, item.currency)}  →  ${_market(context, item)}',
          style: Theme.of(context).textTheme.titleSmall?.copyWith(color: color),
        ),
        const SizedBox(height: 4),
        Text(
          _priceExplanation(context, item),
          style: Theme.of(
            context,
          ).textTheme.bodySmall?.copyWith(color: colors.muted),
        ),
      ],
    );
  }
}

class _StatusBadge extends StatelessWidget {
  const _StatusBadge({required this.style});

  final _StatusStyle style;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
      decoration: BoxDecoration(
        color: style.background,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        style.label,
        style: Theme.of(context).textTheme.labelMedium?.copyWith(
          color: style.foreground,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({
    required this.filtered,
    required this.onOpenSources,
    required this.onClear,
  });

  final bool filtered;
  final VoidCallback onOpenSources;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return MarkoPanel(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 34),
      child: Column(
        children: [
          Icon(
            filtered
                ? Icons.filter_alt_off_outlined
                : Icons.storefront_outlined,
            size: 32,
            color: colors.muted,
          ),
          const SizedBox(height: 12),
          Text(
            filtered
                ? context.localized(
                    ru: 'По этому фильтру товаров нет',
                    uk: 'За цим фільтром товарів немає',
                  )
                : context.localized(
                    ru: 'Подключите источник товаров',
                    uk: 'Підключіть джерело товарів',
                  ),
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 6),
          Text(
            filtered
                ? context.localized(
                    ru: 'Очистите фильтр или измените запрос.',
                    uk: 'Очистьте фільтр або змініть запит.',
                  )
                : context.localized(
                    ru: 'После синхронизации запустите проверку цен на панели расчёта.',
                    uk: 'Після синхронізації запустіть перевірку цін на панелі розрахунку.',
                  ),
            textAlign: TextAlign.center,
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: colors.muted),
          ),
          const SizedBox(height: 16),
          FilledButton(
            onPressed: filtered ? onClear : onOpenSources,
            child: Text(
              filtered
                  ? context.localized(ru: 'Очистить', uk: 'Очистити')
                  : context.localized(
                      ru: 'Подключить источник',
                      uk: 'Підключити джерело',
                    ),
            ),
          ),
        ],
      ),
    );
  }
}

class _StatusStyle {
  const _StatusStyle(this.label, this.icon, this.foreground, this.background);

  final String label;
  final IconData icon;
  final Color foreground;
  final Color background;
}

_StatusStyle _statusStyle(
  BuildContext context,
  MarkoTheme colors,
  String status,
) {
  return switch (status) {
    'OVERPRICED' => _StatusStyle(
      context.localized(ru: 'Дороже', uk: 'Дорожче'),
      Icons.trending_down_rounded,
      colors.warning,
      colors.warningSoft,
    ),
    'UNDERPRICED' => _StatusStyle(
      context.localized(ru: 'Дешевле', uk: 'Дешевше'),
      Icons.trending_up_rounded,
      colors.positive,
      colors.positiveSoft,
    ),
    'IN_MARKET' => _StatusStyle(
      context.localized(ru: 'В рынке', uk: 'У ринку'),
      Icons.check_circle_outline_rounded,
      colors.positive,
      colors.positiveSoft,
    ),
    'PROCESSING' => _StatusStyle(
      context.localized(ru: 'Считается', uk: 'Розраховується'),
      Icons.sync_rounded,
      colors.brand,
      colors.brandSoft,
    ),
    'NO_DATA' => _StatusStyle(
      context.localized(ru: 'Нет данных', uk: 'Немає даних'),
      Icons.search_off_rounded,
      colors.muted,
      colors.surfaceMuted,
    ),
    _ => _StatusStyle(
      context.localized(ru: 'Проверить', uk: 'Перевірити'),
      Icons.fact_check_outlined,
      colors.negative,
      colors.negativeSoft,
    ),
  };
}

String _money(DecimalValue? value, String currency) {
  if (value == null) return '—';
  return '${value.toStringAsFixed(0)} $currency';
}

String _market(BuildContext context, AttentionProduct item) {
  final low = item.marketLow;
  final high = item.marketHigh;
  if (low == null && high == null) {
    return context.localized(
      ru: 'рынок не определён',
      uk: 'ринок не визначено',
    );
  }
  if (low == null) return _money(high, item.currency);
  if (high == null || low == high) return _money(low, item.currency);
  return '${low.toStringAsFixed(0)}–${high.toStringAsFixed(0)} ${item.currency}';
}

String _priceExplanation(BuildContext context, AttentionProduct item) {
  final difference = item.differencePercent;
  final evidence = item.evidenceCount;
  if (item.status == 'PROCESSING') {
    return context.localized(
      ru: 'Ищем и проверяем предложения конкурентов',
      uk: 'Шукаємо й перевіряємо пропозиції конкурентів',
    );
  }
  if (item.status == 'NO_DATA') {
    return context.localized(
      ru: 'Надёжных предложений пока недостаточно',
      uk: 'Надійних пропозицій поки недостатньо',
    );
  }
  if (item.status == 'REVIEW_REQUIRED') {
    return context.localized(
      ru: 'Проверьте OEM товара или повторите мониторинг',
      uk: 'Перевірте OEM товару або повторіть моніторинг',
    );
  }
  final percent = difference?.abs().toStringAsFixed(1);
  final movement = item.status == 'OVERPRICED'
      ? context.localized(ru: 'выше ориентира', uk: 'вище орієнтира')
      : item.status == 'UNDERPRICED'
      ? context.localized(ru: 'ниже ориентира', uk: 'нижче орієнтира')
      : context.localized(ru: 'соответствует рынку', uk: 'відповідає ринку');
  return [
    if (percent != null) '$percent% $movement' else movement,
    context.localized(
      ru: '$evidence подтверждённых продавцов',
      uk: '$evidence підтверджених продавців',
    ),
  ].join(' · ');
}

String _freshness(BuildContext context, DateTime? value) {
  if (value == null) {
    return context.localized(
      ru: 'Оценки появятся по мере синхронизации товаров.',
      uk: 'Оцінки з’являться під час синхронізації товарів.',
    );
  }
  final local = value.toLocal();
  final minute = local.minute.toString().padLeft(2, '0');
  return context.localized(
    ru: 'Последнее обновление ${local.day}.${local.month} в ${local.hour}:$minute',
    uk: 'Останнє оновлення ${local.day}.${local.month} о ${local.hour}:$minute',
  );
}

String _attentionTitle(BuildContext context, int count) {
  final last = count % 10;
  final lastTwo = count % 100;
  final singular = last == 1 && lastTwo != 11;
  final few = last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14);
  return context.localized(
    ru: singular
        ? '$count позиция требует внимания'
        : few
        ? '$count позиции требуют внимания'
        : '$count позиций требуют внимания',
    uk: singular
        ? '$count позиція потребує уваги'
        : few
        ? '$count позиції потребують уваги'
        : '$count позицій потребують уваги',
  );
}
