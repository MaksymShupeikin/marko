import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/app_language.dart';
import '../../core/app_theme.dart';
import '../../core/marko_ui.dart';
import '../../core/widgets/marko_menu.dart';
import '../fitment/fitment_candidates_panel.dart';
import 'catalog_context_dialog.dart';
import 'pricing_api.dart';
import 'pricing_controller.dart';
import 'pricing_models.dart';
import 'recommendation_decision_dialog.dart';
import 'tier_override_dialog.dart';

class RecommendationsPage extends ConsumerWidget {
  const RecommendationsPage({this.onOpenCatalog, super.key});

  final VoidCallback? onOpenCatalog;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncState = ref.watch(recommendationsControllerProvider);
    return asyncState.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (error, _) => _LoadError(
        message: error.toString(),
        onRetry: () => ref.invalidate(recommendationsControllerProvider),
      ),
      data: (state) => _RecommendationsContent(
        state: state,
        onOpenCatalog: onOpenCatalog,
        onRefresh: () =>
            ref.read(recommendationsControllerProvider.notifier).refresh(),
        onQueue: (queue) => ref
            .read(recommendationsControllerProvider.notifier)
            .setQueue(queue),
        onSort: (sort) =>
            ref.read(recommendationsControllerProvider.notifier).setSort(sort),
      ),
    );
  }
}

class _RecommendationsContent extends StatelessWidget {
  const _RecommendationsContent({
    required this.state,
    required this.onOpenCatalog,
    required this.onRefresh,
    required this.onQueue,
    required this.onSort,
  });

  final RecommendationsState state;
  final VoidCallback? onOpenCatalog;
  final VoidCallback onRefresh;
  final ValueChanged<String> onQueue;
  final ValueChanged<String> onSort;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final recommendations = state.page.items;
    final raiseCount = recommendations.where((item) => item.isRaise).length;
    final lowerCount = recommendations.where((item) => item.isLower).length;
    final reviewCount = recommendations
        .where((item) => item.needsReview)
        .length;
    return RefreshIndicator(
      onRefresh: () async => onRefresh(),
      child: ListView(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 28),
        children: [
          Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 1120),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Wrap(
                    alignment: WrapAlignment.spaceBetween,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    spacing: 16,
                    runSpacing: 14,
                    children: [
                      ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 720),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              context.localized(
                                ru: 'Сравнение цен',
                                uk: 'Порівняння цін',
                              ),
                              style: Theme.of(context).textTheme.headlineMedium,
                            ),
                            const SizedBox(height: 7),
                            Text(
                              context.localized(
                                ru: 'По умолчанию сначала показаны самые большие рекомендуемые изменения. Цена на Prom.ua не меняется автоматически.',
                                uk: 'Спочатку показані найбільші рекомендовані зміни. Ціна на Prom.ua не змінюється автоматично.',
                              ),
                              style: Theme.of(context).textTheme.bodyMedium
                                  ?.copyWith(color: colors.muted),
                            ),
                          ],
                        ),
                      ),
                      IconButton(
                        tooltip: context.localized(
                          ru: 'Обновить',
                          uk: 'Оновити',
                        ),
                        onPressed: onRefresh,
                        icon: const Icon(Icons.refresh_rounded),
                      ),
                    ],
                  ),
                  const SizedBox(height: 22),
                  if (state.error != null) ...[
                    MarkoInlineMessage(
                      message: state.error!,
                      tone: MarkoMessageTone.error,
                    ),
                    const SizedBox(height: 16),
                  ],
                  _SummaryRow(
                    total: state.page.total,
                    raiseCount: raiseCount,
                    lowerCount: lowerCount,
                    reviewCount: reviewCount,
                  ),
                  const SizedBox(height: 18),
                  Wrap(
                    alignment: WrapAlignment.spaceBetween,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    spacing: 16,
                    runSpacing: 12,
                    children: [
                      _QueueFilters(selected: state.queue, onSelected: onQueue),
                      _SortSelector(selected: state.sort, onSelected: onSort),
                    ],
                  ),
                  const SizedBox(height: 16),
                  if (recommendations.isEmpty)
                    _EmptyRecommendations(onOpenCatalog: onOpenCatalog)
                  else
                    ...recommendations.map(
                      (recommendation) => Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: _RecommendationCard(
                          recommendation: recommendation,
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _SortSelector extends StatelessWidget {
  const _SortSelector({required this.selected, required this.onSelected});

  final String selected;
  final ValueChanged<String> onSelected;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final entries = <MarkoMenuEntry<String>>[
      MarkoMenuEntry(
        value: 'ABSOLUTE_RECOMMENDED_CHANGE',
        label: context.localized(ru: 'Макс. изменение, ₴', uk: 'Макс. зміна, ₴'),
        icon: Icons.swap_vert_rounded,
      ),
      MarkoMenuEntry(
        value: 'PERCENT_RECOMMENDED_CHANGE',
        label: context.localized(ru: 'Макс. изменение, %', uk: 'Макс. зміна, %'),
        icon: Icons.percent_rounded,
      ),
      MarkoMenuEntry(
        value: 'EXPECTED_GROSS_UPLIFT',
        label: context.localized(
          ru: 'Потенциал валовой маржи',
          uk: 'Потенціал валової маржі',
        ),
        icon: Icons.trending_up_rounded,
      ),
      MarkoMenuEntry(
        value: 'CLEARANCE_CAPITAL_LOCK',
        label: context.localized(
          ru: 'Замороженный капитал',
          uk: 'Заморожений капітал',
        ),
        icon: Icons.inventory_2_outlined,
      ),
      MarkoMenuEntry(
        value: 'REVIEW_PRIORITY',
        label: context.localized(
          ru: 'Приоритет проверки',
          uk: 'Пріоритет перевірки',
        ),
        icon: Icons.flag_outlined,
      ),
    ];
    final current = entries.firstWhere(
      (entry) => entry.value == selected,
      orElse: () => entries.first,
    );

    return MarkoMenuButton<String>(
      key: const ValueKey('recommendations-sort'),
      tooltip: context.localized(ru: 'Сортировка', uk: 'Сортування'),
      header: context.localized(ru: 'Сортировка', uk: 'Сортування'),
      selected: selected,
      onSelected: onSelected,
      entries: entries,
      minWidth: 288,
      maxWidth: 340,
      child: Container(
        width: 310,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        decoration: BoxDecoration(
          color: colors.surface,
          borderRadius: BorderRadius.circular(9),
          border: Border.all(color: colors.border),
        ),
        child: Row(
          children: [
            Icon(Icons.sort_rounded, size: 18, color: colors.muted),
            const SizedBox(width: 9),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    context.localized(ru: 'Сортировка', uk: 'Сортування'),
                    style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: colors.muted,
                    ),
                  ),
                  Text(
                    current.label,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: colors.ink,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 6),
            Icon(
              Icons.keyboard_arrow_down_rounded,
              size: 18,
              color: colors.muted,
            ),
          ],
        ),
      ),
    );
  }
}

class _SummaryRow extends StatelessWidget {
  const _SummaryRow({
    required this.total,
    required this.raiseCount,
    required this.lowerCount,
    required this.reviewCount,
  });

  final int total;
  final int raiseCount;
  final int lowerCount;
  final int reviewCount;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth >= 760 ? 4 : 2;
        final width = (constraints.maxWidth - (columns - 1) * 12) / columns;
        return Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            _SummaryMetric(
              width: width,
              value: '$total',
              label: context.localized(ru: 'Всего', uk: 'Усього'),
            ),
            _SummaryMetric(
              width: width,
              value: '$raiseCount',
              label: context.localized(ru: 'Поднять', uk: 'Підвищити'),
              tone: _Tone.positive,
            ),
            _SummaryMetric(
              width: width,
              value: '$lowerCount',
              label: context.localized(ru: 'Снизить', uk: 'Знизити'),
              tone: _Tone.warning,
            ),
            _SummaryMetric(
              width: width,
              value: '$reviewCount',
              label: context.localized(ru: 'Проверить', uk: 'Перевірити'),
              tone: _Tone.negative,
            ),
          ],
        );
      },
    );
  }
}

enum _Tone { neutral, positive, warning, negative }

class _SummaryMetric extends StatelessWidget {
  const _SummaryMetric({
    required this.width,
    required this.value,
    required this.label,
    this.tone = _Tone.neutral,
  });

  final double width;
  final String value;
  final String label;
  final _Tone tone;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final foreground = switch (tone) {
      _Tone.positive => colors.positive,
      _Tone.warning => colors.warning,
      _Tone.negative => colors.negative,
      _ => colors.ink,
    };
    return SizedBox(
      width: width,
      child: MarkoPanel(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              value,
              style: Theme.of(
                context,
              ).textTheme.headlineSmall?.copyWith(color: foreground),
            ),
            const SizedBox(height: 4),
            Text(label, style: Theme.of(context).textTheme.bodySmall),
          ],
        ),
      ),
    );
  }
}

class _QueueFilters extends StatelessWidget {
  const _QueueFilters({required this.selected, required this.onSelected});

  final String selected;
  final ValueChanged<String> onSelected;

  @override
  Widget build(BuildContext context) {
    final options = <(String, String)>[
      ('all', context.localized(ru: 'Все', uk: 'Усі')),
      (
        'raise',
        context.localized(ru: 'Недополученная маржа', uk: 'Недоотримана маржа'),
      ),
      (
        'clearance',
        context.localized(
          ru: 'Высвобождение капитала',
          uk: 'Вивільнення капіталу',
        ),
      ),
      (
        'review',
        context.localized(ru: 'Проверить вручную', uk: 'Перевірити вручну'),
      ),
      ('hold', context.localized(ru: 'Без изменения', uk: 'Без змін')),
    ];
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: options
          .map(
            (option) => ChoiceChip(
              label: Text(option.$2),
              selected: selected == option.$1,
              onSelected: (_) => onSelected(option.$1),
            ),
          )
          .toList(growable: false),
    );
  }
}

class _RecommendationCard extends ConsumerStatefulWidget {
  const _RecommendationCard({required this.recommendation});

  final PricingRecommendation recommendation;

  @override
  ConsumerState<_RecommendationCard> createState() =>
      _RecommendationCardState();
}

class _RecommendationCardState extends ConsumerState<_RecommendationCard> {
  Future<List<RecommendationEvidence>>? _evidence;
  bool _savingDecision = false;
  bool _verifyingReplay = false;
  RecommendationReplay? _replay;

  @override
  Widget build(BuildContext context) {
    final recommendation = widget.recommendation;
    final colors = MarkoTheme.of(context);
    final (foreground, background, icon) = recommendation.isRaise
        ? (colors.positive, colors.positiveSoft, Icons.trending_up_rounded)
        : recommendation.isLower
        ? (colors.warning, colors.warningSoft, Icons.trending_down_rounded)
        : recommendation.needsReview
        ? (colors.negative, colors.negativeSoft, Icons.fact_check_outlined)
        : (colors.muted, colors.surfaceMuted, Icons.horizontal_rule_rounded);
    return MarkoPanel(
      padding: EdgeInsets.zero,
      child: ExpansionTile(
        onExpansionChanged: (expanded) {
          if (expanded && _evidence == null) {
            setState(() {
              _evidence = ref
                  .read(pricingApiProvider)
                  .getEvidence(recommendation.id);
            });
          }
        },
        tilePadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 8),
        childrenPadding: const EdgeInsets.fromLTRB(18, 0, 18, 18),
        leading: Container(
          width: 40,
          height: 40,
          decoration: BoxDecoration(
            color: background,
            borderRadius: BorderRadius.circular(9),
          ),
          alignment: Alignment.center,
          child: Icon(icon, color: foreground, size: 21),
        ),
        title: Row(
          children: [
            Expanded(
              child: Text(
                recommendation.name,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
            const SizedBox(width: 12),
            _ActionBadge(
              label: _actionLabel(context, recommendation.action),
              foreground: foreground,
              background: background,
            ),
          ],
        ),
        subtitle: Padding(
          padding: const EdgeInsets.only(top: 7),
          child: Wrap(
            spacing: 14,
            runSpacing: 5,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text(
                'SKU ${recommendation.sku} · OE ${recommendation.oe}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              Text(
                _priceDecision(context, recommendation),
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: foreground,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ),
        children: [
          const Divider(),
          const SizedBox(height: 14),
          LayoutBuilder(
            builder: (context, constraints) {
              final compact = constraints.maxWidth < 680;
              final evidence = _Evidence(recommendation: recommendation);
              final health = _DataHealth(recommendation: recommendation);
              if (compact) {
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [evidence, const SizedBox(height: 18), health],
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: evidence),
                  const SizedBox(width: 28),
                  Expanded(child: health),
                ],
              );
            },
          ),
          const SizedBox(height: 16),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              OutlinedButton.icon(
                onPressed: _editContext,
                icon: const Icon(Icons.inventory_2_outlined, size: 18),
                label: Text(
                  context.localized(
                    ru: 'Контекст склада',
                    uk: 'Контекст складу',
                  ),
                ),
              ),
              OutlinedButton.icon(
                onPressed: _verifyingReplay ? null : _verifyReplay,
                icon: _verifyingReplay
                    ? const SizedBox.square(
                        dimension: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.verified_outlined, size: 18),
                label: Text(
                  context.localized(
                    ru: 'Проверить replay',
                    uk: 'Перевірити replay',
                  ),
                ),
              ),
              if (recommendation.automaticEligible &&
                  recommendation.recommendedPrice != null) ...[
                FilledButton.icon(
                  onPressed: _savingDecision
                      ? null
                      : () => _recordDecision('accepted'),
                  icon: const Icon(Icons.check_rounded, size: 18),
                  label: Text(context.localized(ru: 'Принять', uk: 'Прийняти')),
                ),
              ],
              OutlinedButton.icon(
                onPressed: _savingDecision
                    ? null
                    : () => _recordDecision('overridden'),
                icon: const Icon(Icons.edit_outlined, size: 18),
                label: Text(
                  recommendation.automaticEligible
                      ? context.localized(ru: 'Своя цена', uk: 'Своя ціна')
                      : context.localized(
                          ru: 'Ручная цена (audit)',
                          uk: 'Ручна ціна (audit)',
                        ),
                ),
              ),
              TextButton(
                onPressed: _savingDecision
                    ? null
                    : () => _recordDecision('rejected'),
                child: Text(
                  context.localized(ru: 'Отклонить', uk: 'Відхилити'),
                ),
              ),
            ],
          ),
          if (_replay != null) ...[
            const SizedBox(height: 12),
            _ReplayStatus(replay: _replay!),
          ],
          if (_evidence != null) ...[
            const SizedBox(height: 18),
            const Divider(),
            const SizedBox(height: 14),
            _MarketEvidenceList(
              future: _evidence!,
              normalizedOffers: recommendation.normalizedOffersById,
              onOverride: _overrideTier,
            ),
            const SizedBox(height: 18),
            const Divider(),
            const SizedBox(height: 14),
            FitmentCandidatesPanel(catalogItemId: recommendation.catalogItemId),
          ],
        ],
      ),
    );
  }

  String _priceDecision(BuildContext context, PricingRecommendation item) {
    final target = item.recommendedPrice;
    if (target == null && !item.automaticEligible) {
      return context.localized(
        ru: '${_money(item.currentPrice)} — автоцена не сформирована',
        uk: '${_money(item.currentPrice)} — автоціну не сформовано',
      );
    }
    if (target == null) {
      return context.localized(
        ru: '${_money(item.currentPrice)} — без изменений',
        uk: '${_money(item.currentPrice)} — без змін',
      );
    }
    final change =
        item.absoluteRecommendedChange ?? (target - item.currentPrice).abs();
    final percent =
        item.percentageRecommendedChange ??
        (item.currentPrice == 0 ? 0 : change / item.currentPrice);
    final sign = target >= item.currentPrice ? '+' : '−';
    return '${_money(item.currentPrice)} → ${_money(target)} · '
        '$sign${_money(change)} (${(percent * 100).toStringAsFixed(1)}%)';
  }

  Future<void> _editContext() async {
    final recommendation = widget.recommendation;
    final values = await showCatalogContextDialog(
      context,
      initialStatus: recommendation.stockStatus,
      initialContext: recommendation.contextSnapshot,
    );
    if (values == null || !mounted) return;
    final saved = await ref
        .read(recommendationsControllerProvider.notifier)
        .saveCatalogContext(recommendation.catalogItemId, values);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          saved
              ? context.localized(
                  ru: 'Контекст сохранён и будет учтён в следующем прогоне.',
                  uk: 'Контекст збережено, його буде враховано в наступному прогоні.',
                )
              : context.localized(
                  ru: 'Не удалось сохранить контекст.',
                  uk: 'Не вдалося зберегти контекст.',
                ),
        ),
      ),
    );
  }

  Future<void> _recordDecision(String decision) async {
    final values = await showRecommendationDecisionDialog(
      context,
      recommendation: widget.recommendation,
      decision: decision,
    );
    if (values == null || !mounted) return;
    setState(() => _savingDecision = true);
    final saved = await ref
        .read(recommendationsControllerProvider.notifier)
        .recordDecision(widget.recommendation.id, values);
    if (!mounted) return;
    setState(() => _savingDecision = false);
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          saved
              ? context.localized(
                  ru: 'Решение записано в audit trail.',
                  uk: 'Рішення записано в audit trail.',
                )
              : context.localized(
                  ru: 'Не удалось записать решение.',
                  uk: 'Не вдалося записати рішення.',
                ),
        ),
      ),
    );
  }

  Future<void> _verifyReplay() async {
    setState(() => _verifyingReplay = true);
    try {
      final replay = await ref
          .read(pricingApiProvider)
          .verifyReplay(widget.recommendation.id);
      if (!mounted) return;
      setState(() {
        _replay = replay;
        _verifyingReplay = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _verifyingReplay = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            context.localized(
              ru: 'Replay недоступен: $error',
              uk: 'Replay недоступний: $error',
            ),
          ),
        ),
      );
    }
  }

  Future<void> _overrideTier(RecommendationEvidence evidence) async {
    final override = await showTierOverrideDialog(
      context,
      currentTier: evidence.tier,
    );
    if (override == null || !mounted) return;
    try {
      await ref
          .read(pricingApiProvider)
          .overrideTier(
            evidence.observationId,
            tier: override.tier,
            reason: override.reason,
          );
      if (!mounted) return;
      setState(() {
        _evidence = ref
            .read(pricingApiProvider)
            .getEvidence(widget.recommendation.id);
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            context.localized(
              ru: 'Tier override сохранён. Новый run пересчитает цену.',
              uk: 'Tier override збережено. Новий run перерахує ціну.',
            ),
          ),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            context.localized(
              ru: 'Не удалось сохранить: $error',
              uk: 'Не вдалося зберегти: $error',
            ),
          ),
        ),
      );
    }
  }
}

class _ReplayStatus extends StatelessWidget {
  const _ReplayStatus({required this.replay});

  final RecommendationReplay replay;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final exact = replay.exactMatch;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: exact ? colors.positiveSoft : colors.negativeSoft,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          Icon(
            exact ? Icons.verified_rounded : Icons.warning_amber_rounded,
            color: exact ? colors.positive : colors.negative,
            size: 19,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              exact
                  ? context.localized(
                      ru: 'Replay совпал: ${replay.contractVersion}',
                      uk: 'Replay збігається: ${replay.contractVersion}',
                    )
                  : context.localized(
                      ru: 'Обнаружен drift: ${replay.mismatches.keys.join(', ')}',
                      uk: 'Виявлено drift: ${replay.mismatches.keys.join(', ')}',
                    ),
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: exact ? colors.positive : colors.negative,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _MarketEvidenceList extends StatelessWidget {
  const _MarketEvidenceList({
    required this.future,
    required this.normalizedOffers,
    required this.onOverride,
  });

  final Future<List<RecommendationEvidence>> future;
  final Map<String, Map<String, dynamic>> normalizedOffers;
  final Future<void> Function(RecommendationEvidence) onOverride;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return FutureBuilder<List<RecommendationEvidence>>(
      future: future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const LinearProgressIndicator();
        }
        if (snapshot.hasError) {
          return Text(
            context.localized(
              ru: 'Не удалось загрузить доказательства: ${snapshot.error}',
              uk: 'Не вдалося завантажити докази: ${snapshot.error}',
            ),
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: colors.negative),
          );
        }
        final items = snapshot.data ?? const [];
        if (items.isEmpty) {
          return Text(
            context.localized(
              ru: 'Валидных рыночных предложений нет.',
              uk: 'Валідних ринкових пропозицій немає.',
            ),
            style: Theme.of(context).textTheme.bodySmall,
          );
        }
        final laneItems = items.toList(growable: false)
          ..sort(
            (left, right) => _cohortRank(
              left.cohortRole,
            ).compareTo(_cohortRank(right.cohortRole)),
          );
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              context.localized(
                ru: 'Evidence: целевой рынок, KEMP reference и исключения',
                uk: 'Evidence: цільовий ринок, KEMP reference та виключення',
              ),
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 10),
            ...laneItems.map((item) {
              final normalized = normalizedOffers[item.observationId];
              final normalizedPrice =
                  double.tryParse(
                    normalized?['normalized_price']?.toString() ?? '',
                  ) ??
                  item.normalizedPrice;
              final multiplier =
                  double.tryParse(
                    normalized?['multiplier']?.toString() ?? '',
                  ) ??
                  item.multiplier;
              final coefficientLine =
                  normalizedPrice != null && multiplier != null
                  ? context.localized(
                      ru:
                          'KEMP-эквивалент: ${_money(normalizedPrice)} · '
                          'm=${multiplier.toStringAsFixed(2)}',
                      uk:
                          'KEMP-еквівалент: ${_money(normalizedPrice)} · '
                          'm=${multiplier.toStringAsFixed(2)}',
                    )
                  : context.localized(
                      ru: 'Нормализация: не участвует',
                      uk: 'Нормалізація: не бере участі',
                    );
              final coefficientEvidence = item.coefficientModel == null
                  ? context.localized(
                      ru: 'Коэффициент: нет валидированного evidence',
                      uk: 'Коефіцієнт: немає валідованого evidence',
                    )
                  : '${item.coefficientModel} · coefficient confidence '
                        '${((item.coefficientConfidence ?? 0) * 100).round()}%';
              final listingUri = Uri.tryParse(item.url);
              final listingIsOpenable =
                  listingUri != null &&
                  (listingUri.scheme == 'http' ||
                      listingUri.scheme == 'https') &&
                  listingUri.host.isNotEmpty;
              return InkWell(
                onTap: !listingIsOpenable
                    ? null
                    : () => launchUrl(
                        listingUri,
                        mode: LaunchMode.externalApplication,
                      ),
                borderRadius: BorderRadius.circular(8),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              item.sellerName,
                              style: Theme.of(context).textTheme.bodyMedium
                                  ?.copyWith(fontWeight: FontWeight.w600),
                            ),
                            const SizedBox(height: 2),
                            Text(
                              '${_cohortLabel(context, item.cohortRole)} · ${item.targetEffect}',
                              style: Theme.of(context).textTheme.bodySmall
                                  ?.copyWith(
                                    color: item.affectsTargetMedian
                                        ? colors.positive
                                        : colors.warning,
                                    fontWeight: FontWeight.w700,
                                  ),
                            ),
                            Text(
                              '${_tierLabel(context, item.tier)} · match ${(item.matchConfidence * 100).round()}% · tier ${(item.tierConfidence * 100).round()}%',
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                            Text(
                              '$coefficientEvidence · '
                              '${item.ageHours == null ? context.localized(ru: 'возраст evidence не зафиксирован', uk: 'вік evidence не зафіксовано') : context.localized(ru: '${item.ageHours!.toStringAsFixed(1)} ч.', uk: '${item.ageHours!.toStringAsFixed(1)} год.')}',
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                            Text(
                              '${context.localized(ru: 'Состояние', uk: 'Стан')}: ${item.conditionState}'
                              '${item.conditionRaw == null ? '' : ' · ${item.conditionRaw}'}',
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                            if (item.exclusionReason != null)
                              Text(
                                '${context.localized(ru: 'Исключено', uk: 'Виключено')}: ${_reasonLabel(context, item.exclusionReason!)}',
                                style: Theme.of(context).textTheme.bodySmall
                                    ?.copyWith(color: colors.negative),
                              ),
                            if (item.crossCandidates.isNotEmpty)
                              Text(
                                context.localized(
                                  ru: 'Cross candidates: ${item.crossCandidates.length} · phase 2 · не automatic identity',
                                  uk: 'Cross candidates: ${item.crossCandidates.length} · phase 2 · не automatic identity',
                                ),
                                style: Theme.of(context).textTheme.bodySmall,
                              ),
                            if (item.url.isEmpty)
                              Text(
                                'URL: ${item.urlAbsenceReason ?? 'NOT_AVAILABLE'}',
                                style: Theme.of(context).textTheme.bodySmall,
                              ),
                            Text(
                              item.automaticEligible
                                  ? context.localized(
                                      ru: 'Сопоставимость: verified',
                                      uk: 'Зіставність: verified',
                                    )
                                  : context.localized(
                                      ru: 'Сопоставимость: manual review',
                                      uk: 'Зіставність: manual review',
                                    ),
                              style: Theme.of(context).textTheme.bodySmall
                                  ?.copyWith(
                                    color: item.automaticEligible
                                        ? colors.positive
                                        : colors.warning,
                                  ),
                            ),
                          ],
                        ),
                      ),
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          Text(
                            _money(item.price),
                            style: Theme.of(context).textTheme.titleMedium,
                          ),
                          Text(
                            coefficientLine,
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                        ],
                      ),
                      if (item.url.isNotEmpty) ...[
                        const SizedBox(width: 8),
                        Icon(
                          Icons.open_in_new_rounded,
                          size: 16,
                          color: colors.brand,
                        ),
                      ],
                      IconButton(
                        tooltip: context.localized(
                          ru: 'Уточнить tier',
                          uk: 'Уточнити tier',
                        ),
                        onPressed: () => onOverride(item),
                        icon: const Icon(Icons.rule_rounded, size: 18),
                      ),
                    ],
                  ),
                ),
              );
            }),
          ],
        );
      },
    );
  }
}

class _ActionBadge extends StatelessWidget {
  const _ActionBadge({
    required this.label,
    required this.foreground,
    required this.background,
  });

  final String label;
  final Color foreground;
  final Color background;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(7),
      ),
      child: Text(
        label,
        style: Theme.of(context).textTheme.labelMedium?.copyWith(
          color: foreground,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

class _Evidence extends StatelessWidget {
  const _Evidence({required this.recommendation});

  final PricingRecommendation recommendation;

  @override
  Widget build(BuildContext context) {
    final estimator = recommendation.calculationTrace['fair_price_estimator']
        ?.toString();
    final outlierFilter = recommendation.calculationTrace['outlier_filter']
        ?.toString();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          context.localized(ru: 'Расчёт', uk: 'Розрахунок'),
          style: Theme.of(context).textTheme.titleMedium,
        ),
        const SizedBox(height: 11),
        _KeyValue(
          label: context.localized(
            ru: 'Справедливая цена',
            uk: 'Справедлива ціна',
          ),
          value: recommendation.fairPrice == null
              ? context.localized(ru: 'не рассчитана', uk: 'не розрахована')
              : _money(recommendation.fairPrice!),
        ),
        _KeyValue(
          label: context.localized(
            ru: 'Рыночный диапазон',
            uk: 'Ринковий діапазон',
          ),
          value: recommendation.lowerBound == null
              ? '—'
              : '${_money(recommendation.lowerBound!)} — ${_money(recommendation.upperBound!)}',
        ),
        _KeyValue(
          label: context.localized(ru: 'Приоритет', uk: 'Пріоритет'),
          value: _priorityLabel(context, recommendation),
        ),
        _KeyValue(
          label: 'Evidence lanes',
          value:
              '${recommendation.rawCompetitorCount} raw · '
              '${recommendation.targetMarketCount} target · '
              '${recommendation.kempReferenceCount} KEMP ref · '
              '${recommendation.ownedStoreCount} owned · '
              '${recommendation.rejectedCount} rejected',
        ),
        if (recommendation.sensitivity != null)
          _KeyValue(
            label: 'Sensitivity',
            value: '${(recommendation.sensitivity! * 100).toStringAsFixed(1)}%',
          ),
        if (estimator != null)
          _KeyValue(
            label: context.localized(
              ru: 'Робастная модель',
              uk: 'Робастна модель',
            ),
            value: '$estimator + ${outlierFilter ?? 'none'}',
          ),
        const SizedBox(height: 8),
        Text(
          _reasonSummary(context, recommendation),
          style: Theme.of(context).textTheme.bodySmall,
        ),
        if (recommendation.excludedObservations.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text(
            '${context.localized(ru: 'Исключено', uk: 'Виключено')}: '
            '${_excludedSummary(context, recommendation.excludedObservations)}',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ],
    );
  }
}

class _DataHealth extends StatelessWidget {
  const _DataHealth({required this.recommendation});

  final PricingRecommendation recommendation;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final confidenceColor = recommendation.confidence >= 0.65
        ? colors.positive
        : recommendation.confidence >= 0.55
        ? colors.warning
        : colors.negative;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Text(
              context.localized(ru: 'Качество данных', uk: 'Якість даних'),
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const Spacer(),
            Text(
              '${(recommendation.confidence * 100).round()}% · ${recommendation.confidenceGrade}',
              style: Theme.of(
                context,
              ).textTheme.labelLarge?.copyWith(color: confidenceColor),
            ),
          ],
        ),
        const SizedBox(height: 10),
        LinearProgressIndicator(
          value: recommendation.confidence.clamp(0, 1),
          color: confidenceColor,
        ),
        const SizedBox(height: 12),
        _KeyValue(
          label: context.localized(
            ru: 'Валидных конкурентов',
            uk: 'Валідних конкурентів',
          ),
          value: '${recommendation.competitorCount}',
        ),
        _KeyValue(
          label: context.localized(
            ru: 'Видимых / verified sellers',
            uk: 'Видимих / verified sellers',
          ),
          value:
              '${recommendation.rawCompetitorCount} / ${recommendation.verifiedSellerCount}',
        ),
        _KeyValue(
          label: 'Automatic eligibility',
          value: recommendation.automaticEligible ? 'verified' : 'blocked',
        ),
        if (recommendation.comparabilityPolicyId != null)
          _KeyValue(
            label: 'Comparability policy',
            value: recommendation.comparabilityPolicyId!,
          ),
        _KeyValue(
          label: context.localized(
            ru: 'Эффективная выборка',
            uk: 'Ефективна вибірка',
          ),
          value: recommendation.effectiveCompetitorCount.toStringAsFixed(2),
        ),
        _KeyValue(
          label: 'Action gates',
          value: recommendation.actionGatesPassed
              ? context.localized(ru: 'пройдены', uk: 'пройдено')
              : context.localized(ru: 'не пройдены', uk: 'не пройдено'),
        ),
        _KeyValue(
          label: context.localized(ru: 'Слабое место', uk: 'Слабке місце'),
          value: _factorLabel(context, recommendation.weakestFactor),
        ),
        const SizedBox(height: 6),
        Wrap(
          spacing: 8,
          runSpacing: 6,
          children: recommendation.factorScores.entries
              .map(
                (entry) => Chip(
                  visualDensity: VisualDensity.compact,
                  label: Text(
                    '${_factorLabel(context, entry.key)} ${(entry.value * 100).round()}%',
                  ),
                ),
              )
              .toList(growable: false),
        ),
      ],
    );
  }
}

class _KeyValue extends StatelessWidget {
  const _KeyValue({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 7),
      child: Row(
        children: [
          Expanded(
            child: Text(
              label,
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: colors.muted),
            ),
          ),
          const SizedBox(width: 12),
          Text(value, style: Theme.of(context).textTheme.bodyMedium),
        ],
      ),
    );
  }
}

class _EmptyRecommendations extends StatelessWidget {
  const _EmptyRecommendations({required this.onOpenCatalog});

  final VoidCallback? onOpenCatalog;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return MarkoPanel(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 40),
      child: Column(
        children: [
          Icon(Icons.price_check_rounded, size: 38, color: colors.brand),
          const SizedBox(height: 14),
          Text(
            context.localized(
              ru: 'Пока нет рекомендаций',
              uk: 'Рекомендацій поки немає',
            ),
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 7),
          Text(
            context.localized(
              ru: 'Подключите магазины и дождитесь заполнения каталога.',
              uk: 'Підключіть магазини та дочекайтеся наповнення каталогу.',
            ),
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodyMedium,
          ),
          if (onOpenCatalog != null) ...[
            const SizedBox(height: 18),
            FilledButton.icon(
              onPressed: onOpenCatalog,
              icon: const Icon(Icons.upload_file_rounded, size: 18),
              label: Text(
                context.localized(
                  ru: 'Открыть каталог',
                  uk: 'Відкрити каталог',
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _LoadError extends StatelessWidget {
  const _LoadError({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520),
        child: MarkoInlineMessage(
          message: message,
          tone: MarkoMessageTone.error,
          action: TextButton(
            onPressed: onRetry,
            child: Text(context.localized(ru: 'Повторить', uk: 'Повторити')),
          ),
        ),
      ),
    );
  }
}

String _money(double value) => '${value.toStringAsFixed(0)} ₴';

int _cohortRank(String role) => switch (role) {
  'TARGET_MARKET' => 0,
  'KEMP_REFERENCE' => 1,
  'OWNED_STORE' => 2,
  'USED_REJECTED' => 3,
  'DUMPING_DIAGNOSTIC' => 4,
  'MANUAL_REVIEW' => 5,
  _ => 6,
};

String _actionLabel(BuildContext context, String action) => switch (action) {
  'RAISE' => context.localized(ru: 'Поднять цену', uk: 'Підвищити ціну'),
  'LOWER' => context.localized(ru: 'Снизить цену', uk: 'Знизити ціну'),
  'HOLD' => context.localized(ru: 'Оставить', uk: 'Залишити'),
  'MANUAL_REVIEW' => context.localized(
    ru: 'Проверить вручную',
    uk: 'Перевірити вручну',
  ),
  'INSUFFICIENT_DATA' => context.localized(ru: 'Мало данных', uk: 'Мало даних'),
  _ => action,
};

String _priorityLabel(
  BuildContext context,
  PricingRecommendation recommendation,
) => switch (recommendation.priorityScoreType) {
  'gross_uplift_opportunity' => context.localized(
    ru: '${recommendation.priorityScore.toStringAsFixed(0)} ₴/мес. с учётом confidence',
    uk: '${recommendation.priorityScore.toStringAsFixed(0)} ₴/міс. з урахуванням confidence',
  ),
  'clearance_priority' => context.localized(
    ru: '${recommendation.priorityScore.toStringAsFixed(0)} ₴ замороженного капитала',
    uk: '${recommendation.priorityScore.toStringAsFixed(0)} ₴ замороженого капіталу',
  ),
  'retail_exposure_proxy' =>
    '${recommendation.priorityScore.toStringAsFixed(2)} · stock exposure proxy',
  'gap_confidence_proxy' =>
    '${recommendation.priorityScore.toStringAsFixed(3)} · gap/confidence proxy',
  _ => '—',
};

String _reasonSummary(
  BuildContext context,
  PricingRecommendation recommendation,
) {
  if (recommendation.reasonCodes.isEmpty) {
    return context.localized(ru: 'Расчёт завершён', uk: 'Розрахунок завершено');
  }
  return recommendation.reasonCodes
      .map((code) => _reasonLabel(context, code))
      .take(2)
      .join(' · ');
}

String _reasonLabel(BuildContext context, String code) => switch (code) {
  'MARKET_SUPPORTS_RAISE' => context.localized(
    ru: 'рынок поддерживает повышение',
    uk: 'ринок підтримує підвищення',
  ),
  'MARKET_NOT_ABOVE_RAISE_THRESHOLD' => context.localized(
    ru: 'рынок не выше текущей цены',
    uk: 'ринок не вище поточної ціни',
  ),
  'CLEARANCE_MARKDOWN' => context.localized(
    ru: 'цена для высвобождения капитала',
    uk: 'ціна для вивільнення капіталу',
  ),
  'TOO_FEW_COMPETITORS' ||
  'TOO_FEW_COMPETITORS_FOR_ACTION' => context.localized(
    ru: 'мало валидных конкурентов',
    uk: 'мало валідних конкурентів',
  ),
  'LOW_CONFIDENCE' => context.localized(
    ru: 'низкая уверенность',
    uk: 'низька впевненість',
  ),
  'LOW_COVERAGE' => context.localized(ru: 'мало данных', uk: 'мало даних'),
  'LOW_DISPERSION' || 'HIGH_DISPERSION' => context.localized(
    ru: 'слишком большой разброс цен',
    uk: 'надто великий розкид цін',
  ),
  'LOW_FRESHNESS' => context.localized(
    ru: 'данные устарели',
    uk: 'дані застаріли',
  ),
  'LOW_MATCH' => context.localized(
    ru: 'слабое совпадение товаров',
    uk: 'слабкий збіг товарів',
  ),
  'LOW_TIER' => context.localized(
    ru: 'смешались уровни товара',
    uk: 'змішалися рівні товару',
  ),
  'LOW_SOURCE' => context.localized(
    ru: 'низкая надёжность источника',
    uk: 'низька надійність джерела',
  ),
  'SEVERE_DATA_HEALTH_ISSUE' => context.localized(
    ru: 'критическая проблема данных',
    uk: 'критична проблема даних',
  ),
  'BELOW_COST_ONLY_FOR_DEAD_STOCK' => context.localized(
    ru: 'цена ниже себестоимости доступна только для неликвида',
    uk: 'ціна нижче собівартості доступна лише для неліквіду',
  ),
  'MISSING_FLOOR' || 'MISSING_COST' => context.localized(
    ru: 'нужна себестоимость',
    uk: 'потрібна собівартість',
  ),
  'LOW_EFFECTIVE_SAMPLE_SIZE' => context.localized(
    ru: 'мало независимых конкурентов',
    uk: 'мало незалежних конкурентів',
  ),
  'ESTIMATOR_SENSITIVITY' => context.localized(
    ru: 'оценка неустойчива к очистке данных',
    uk: 'оцінка нестійка до очищення даних',
  ),
  'ROBUST_MULTIMODAL_COHORT' => context.localized(
    ru: 'обнаружены разные ценовые кластеры',
    uk: 'виявлено різні цінові кластери',
  ),
  'ROBUST_ESTIMATOR_DISAGREEMENT' => context.localized(
    ru: 'робастные оценки расходятся',
    uk: 'робастні оцінки розходяться',
  ),
  'ROBUST_BASELINE_ABSTENTION_NOT_RELAXABLE' => context.localized(
    ru: 'новая модель не может обойти baseline abstention',
    uk: 'нова модель не може обійти baseline abstention',
  ),
  'MANUAL_MISSING_COMPARABILITY_EVIDENCE' => context.localized(
    ru: 'нет доказательств сопоставимости',
    uk: 'немає доказів зіставності',
  ),
  'MANUAL_MISSING_OE_PROVENANCE' => context.localized(
    ru: 'нет проверенного OE',
    uk: 'немає перевіреного OE',
  ),
  'MANUAL_MISSING_STABLE_SELLER_ID' => context.localized(
    ru: 'нет стабильного ID продавца',
    uk: 'немає стабільного ID продавця',
  ),
  'MANUAL_MISSING_SOURCE_PROVENANCE' => context.localized(
    ru: 'нет проверенного source evidence',
    uk: 'немає перевіреного source evidence',
  ),
  'MANUAL_MISSING_RAW_CURRENCY' => context.localized(
    ru: 'валюта не указана в source',
    uk: 'валюту не вказано в source',
  ),
  'REJECTED_IDENTITY_CONFLICT' => context.localized(
    ru: 'конфликт identity товара',
    uk: 'конфлікт identity товару',
  ),
  'REJECTED_COMPARABILITY_CONFLICT' => context.localized(
    ru: 'коммерчески несопоставимые товары',
    uk: 'комерційно незрівнянні товари',
  ),
  'MISSING_BELOW_COST_AUTHORIZATION' => context.localized(
    ru: 'нет полного подтверждения продажи ниже себестоимости',
    uk: 'немає повного підтвердження продажу нижче собівартості',
  ),
  'MANUAL_REVIEW_REQUIRED' => context.localized(
    ru: 'требуется ручная проверка',
    uk: 'потрібна ручна перевірка',
  ),
  _ => code.toLowerCase().replaceAll('_', ' '),
};

String _tierLabel(BuildContext context, String tier) => switch (tier) {
  'oem' => 'OEM',
  'oes' => 'OES',
  'aftermarket_a' => 'Aftermarket A',
  'aftermarket_b' => 'Aftermarket B',
  'budget' => context.localized(ru: 'Бюджет', uk: 'Бюджет'),
  'kemp' => 'KEMP',
  'used' => context.localized(ru: 'б/у', uk: 'вживане'),
  _ => context.localized(ru: 'не определён', uk: 'не визначено'),
};

String _cohortLabel(BuildContext context, String role) => switch (role) {
  'TARGET_MARKET' => context.localized(
    ru: 'Целевой рынок',
    uk: 'Цільовий ринок',
  ),
  'KEMP_REFERENCE' => 'KEMP reference',
  'OWNED_STORE' => context.localized(ru: 'Свой магазин', uk: 'Свій магазин'),
  'USED_REJECTED' => context.localized(
    ru: 'Б/у — исключено',
    uk: 'Вживане — виключено',
  ),
  'DUMPING_DIAGNOSTIC' => 'KEMP dumping diagnostic',
  'HARD_REJECTED' => context.localized(ru: 'Отклонено', uk: 'Відхилено'),
  _ => context.localized(ru: 'Ручная проверка', uk: 'Ручна перевірка'),
};

String _factorLabel(BuildContext context, String? value) => switch (value) {
  'coverage' => context.localized(ru: 'покрытие', uk: 'покриття'),
  'dispersion' => context.localized(ru: 'разброс цен', uk: 'розкид цін'),
  'freshness' => context.localized(ru: 'свежесть', uk: 'свіжість'),
  'match' => context.localized(ru: 'совпадение', uk: 'збіг'),
  'tier' => context.localized(ru: 'уровень товара', uk: 'рівень товару'),
  'source' => context.localized(ru: 'источник', uk: 'джерело'),
  null => context.localized(ru: 'нет', uk: 'немає'),
  _ => value,
};

String _excludedSummary(
  BuildContext context,
  List<Map<String, dynamic>> excluded,
) {
  final counts = <String, int>{};
  for (final item in excluded) {
    final reason = item['reason']?.toString() ?? 'UNKNOWN';
    counts[reason] = (counts[reason] ?? 0) + 1;
  }
  final entries = counts.entries.toList()
    ..sort((left, right) {
      final byCount = right.value.compareTo(left.value);
      return byCount != 0 ? byCount : left.key.compareTo(right.key);
    });
  return entries
      .take(4)
      .map((entry) => '${_reasonLabel(context, entry.key)}: ${entry.value}')
      .join(' · ');
}
