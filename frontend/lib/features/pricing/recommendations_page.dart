import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/app_theme.dart';
import '../../core/marko_ui.dart';
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
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Какую цену поставить сейчас',
                            style: Theme.of(context).textTheme.headlineMedium,
                          ),
                          const SizedBox(height: 7),
                          Text(
                            'По умолчанию сначала показаны самые большие рекомендуемые изменения. Цена на Prom.ua не меняется автоматически.',
                            style: Theme.of(context).textTheme.bodyMedium
                                ?.copyWith(color: colors.muted),
                          ),
                        ],
                      ),
                      IconButton(
                        tooltip: 'Обновить',
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
                      SizedBox(
                        width: 310,
                        child: DropdownButtonFormField<String>(
                          initialValue: state.sort,
                          decoration: const InputDecoration(
                            labelText: 'Сортировка',
                          ),
                          items: const [
                            DropdownMenuItem(
                              value: 'ABSOLUTE_RECOMMENDED_CHANGE',
                              child: Text('Макс. изменение, ₴'),
                            ),
                            DropdownMenuItem(
                              value: 'PERCENT_RECOMMENDED_CHANGE',
                              child: Text('Макс. изменение, %'),
                            ),
                            DropdownMenuItem(
                              value: 'EXPECTED_GROSS_UPLIFT',
                              child: Text('Потенциал валовой маржи'),
                            ),
                            DropdownMenuItem(
                              value: 'CLEARANCE_CAPITAL_LOCK',
                              child: Text('Замороженный капитал'),
                            ),
                            DropdownMenuItem(
                              value: 'REVIEW_PRIORITY',
                              child: Text('Приоритет проверки'),
                            ),
                          ],
                          onChanged: (value) {
                            if (value != null) onSort(value);
                          },
                        ),
                      ),
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
            _SummaryMetric(width: width, value: '$total', label: 'Всего'),
            _SummaryMetric(
              width: width,
              value: '$raiseCount',
              label: 'Поднять',
              tone: _Tone.positive,
            ),
            _SummaryMetric(
              width: width,
              value: '$lowerCount',
              label: 'Снизить',
              tone: _Tone.warning,
            ),
            _SummaryMetric(
              width: width,
              value: '$reviewCount',
              label: 'Проверить',
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
    const options = <(String, String)>[
      ('all', 'Все'),
      ('raise', 'Недополученная маржа'),
      ('clearance', 'Высвобождение капитала'),
      ('review', 'Проверить вручную'),
      ('hold', 'Без изменения'),
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
              label: recommendation.actionLabel,
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
                _priceDecision(recommendation),
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
                label: const Text('Контекст склада'),
              ),
              OutlinedButton.icon(
                onPressed: _verifyingReplay ? null : _verifyReplay,
                icon: _verifyingReplay
                    ? const SizedBox.square(
                        dimension: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.verified_outlined, size: 18),
                label: const Text('Проверить replay'),
              ),
              if (recommendation.automaticEligible &&
                  recommendation.recommendedPrice != null) ...[
                FilledButton.icon(
                  onPressed: _savingDecision
                      ? null
                      : () => _recordDecision('accepted'),
                  icon: const Icon(Icons.check_rounded, size: 18),
                  label: const Text('Принять'),
                ),
              ],
              OutlinedButton.icon(
                onPressed: _savingDecision
                    ? null
                    : () => _recordDecision('overridden'),
                icon: const Icon(Icons.edit_outlined, size: 18),
                label: Text(
                  recommendation.automaticEligible
                      ? 'Своя цена'
                      : 'Ручная цена (audit)',
                ),
              ),
              TextButton(
                onPressed: _savingDecision
                    ? null
                    : () => _recordDecision('rejected'),
                child: const Text('Отклонить'),
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

  String _priceDecision(PricingRecommendation item) {
    final target = item.recommendedPrice;
    if (target == null && !item.automaticEligible) {
      return '${_money(item.currentPrice)} — автоцена не сформирована';
    }
    if (target == null) return '${_money(item.currentPrice)} — без изменений';
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
              ? 'Контекст сохранён и будет учтён в следующем прогоне.'
              : 'Не удалось сохранить контекст.',
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
              ? 'Решение записано в audit trail.'
              : 'Не удалось записать решение.',
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
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('Replay недоступен: $error')));
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
        const SnackBar(
          content: Text('Tier override сохранён. Новый run пересчитает цену.'),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('Не удалось сохранить: $error')));
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
                  ? 'Replay совпал: ${replay.contractVersion}'
                  : 'Обнаружен drift: ${replay.mismatches.keys.join(', ')}',
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
            'Не удалось загрузить доказательства: ${snapshot.error}',
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: colors.negative),
          );
        }
        final items = snapshot.data ?? const [];
        if (items.isEmpty) {
          return Text(
            'Валидных рыночных предложений нет.',
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
              'Evidence: целевой рынок, KEMP reference и исключения',
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
                  ? 'KEMP-эквивалент: ${_money(normalizedPrice)} · '
                        'm=${multiplier.toStringAsFixed(2)}'
                  : 'Нормализация: не участвует';
              final coefficientEvidence = item.coefficientModel == null
                  ? 'Коэффициент: нет валидированного evidence'
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
                              '${item.cohortLabel} · ${item.targetEffect}',
                              style: Theme.of(context).textTheme.bodySmall
                                  ?.copyWith(
                                    color: item.affectsTargetMedian
                                        ? colors.positive
                                        : colors.warning,
                                    fontWeight: FontWeight.w700,
                                  ),
                            ),
                            Text(
                              '${item.tierLabel} · match ${(item.matchConfidence * 100).round()}% · tier ${(item.tierConfidence * 100).round()}%',
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                            Text(
                              '$coefficientEvidence · '
                              '${item.ageHours == null ? 'возраст evidence не зафиксирован' : '${item.ageHours!.toStringAsFixed(1)} ч.'}',
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                            Text(
                              'Состояние: ${item.conditionState}'
                              '${item.conditionRaw == null ? '' : ' · ${item.conditionRaw}'}',
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                            if (item.exclusionReason != null)
                              Text(
                                'Исключено: ${PricingRecommendation.reasonLabel(item.exclusionReason!)}',
                                style: Theme.of(context).textTheme.bodySmall
                                    ?.copyWith(color: colors.negative),
                              ),
                            if (item.crossCandidates.isNotEmpty)
                              Text(
                                'Cross candidates: ${item.crossCandidates.length} · phase 2 · не automatic identity',
                                style: Theme.of(context).textTheme.bodySmall,
                              ),
                            if (item.url.isEmpty)
                              Text(
                                'URL: ${item.urlAbsenceReason ?? 'NOT_AVAILABLE'}',
                                style: Theme.of(context).textTheme.bodySmall,
                              ),
                            Text(
                              item.automaticEligible
                                  ? 'Сопоставимость: verified'
                                  : 'Сопоставимость: manual review',
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
                        tooltip: 'Уточнить tier',
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
        Text('Расчёт', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 11),
        _KeyValue(
          label: 'Справедливая цена',
          value: recommendation.fairPrice == null
              ? 'не рассчитана'
              : _money(recommendation.fairPrice!),
        ),
        _KeyValue(
          label: 'Рыночный диапазон',
          value: recommendation.lowerBound == null
              ? '—'
              : '${_money(recommendation.lowerBound!)} — ${_money(recommendation.upperBound!)}',
        ),
        _KeyValue(label: 'Приоритет', value: recommendation.priorityLabel),
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
            label: 'Робастная модель',
            value: '$estimator + ${outlierFilter ?? 'none'}',
          ),
        const SizedBox(height: 8),
        Text(
          recommendation.reasonSummary,
          style: Theme.of(context).textTheme.bodySmall,
        ),
        if (recommendation.excludedObservations.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text(
            'Исключено: ${_excludedSummary(recommendation.excludedObservations)}',
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
              'Качество данных',
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
          label: 'Валидных конкурентов',
          value: '${recommendation.competitorCount}',
        ),
        _KeyValue(
          label: 'Видимых / verified sellers',
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
          label: 'Эффективная выборка',
          value: recommendation.effectiveCompetitorCount.toStringAsFixed(2),
        ),
        _KeyValue(
          label: 'Action gates',
          value: recommendation.actionGatesPassed ? 'пройдены' : 'не пройдены',
        ),
        _KeyValue(
          label: 'Слабое место',
          value: _factorLabel(recommendation.weakestFactor),
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
                    '${_factorLabel(entry.key)} ${(entry.value * 100).round()}%',
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
            'Пока нет рекомендаций',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 7),
          Text(
            'Импортируйте XLSX-каталог и запустите расчёт.',
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodyMedium,
          ),
          if (onOpenCatalog != null) ...[
            const SizedBox(height: 18),
            FilledButton.icon(
              onPressed: onOpenCatalog,
              icon: const Icon(Icons.upload_file_rounded, size: 18),
              label: const Text('Открыть каталог'),
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
            child: const Text('Повторить'),
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

String _factorLabel(String? value) => switch (value) {
  'coverage' => 'покрытие',
  'dispersion' => 'разброс цен',
  'freshness' => 'свежесть',
  'match' => 'совпадение',
  'tier' => 'уровень товара',
  'source' => 'источник',
  null => 'нет',
  _ => value,
};

String _excludedSummary(List<Map<String, dynamic>> excluded) {
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
      .map(
        (entry) =>
            '${PricingRecommendation.reasonLabel(entry.key)}: ${entry.value}',
      )
      .join(' · ');
}
