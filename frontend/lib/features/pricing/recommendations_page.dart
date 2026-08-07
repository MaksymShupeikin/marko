import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/api_client.dart';
import '../../core/app_language.dart';
import '../../core/app_theme.dart';
import '../../core/marko_ui.dart';
import '../../core/presentation_formatters.dart';
import '../../core/session_expiry.dart';
import '../../core/widgets/marko_menu.dart';
import '../fitment/fitment_candidates_panel.dart';
import 'catalog_context_dialog.dart';
import 'comparability_feedback_dialog.dart';
import 'comparability_review_panel.dart';
import 'discovery_funnel_panel.dart';
import 'pricing_api.dart';
import 'pricing_controller.dart';
import 'pricing_models.dart';
import 'pricing_reason_labels.dart';
import 'recommendation_decision_dialog.dart';
import 'recommendation_export_button.dart';
import 'pricing_run_panel.dart';
import 'tier_override_dialog.dart';

class RecommendationsPage extends ConsumerWidget {
  const RecommendationsPage({
    this.onOpenCatalog,
    this.canAdministerWorkspace = false,
    this.initialRecommendationId,
    this.onOpenRecommendationDeepLink,
    super.key,
  });

  final VoidCallback? onOpenCatalog;
  final bool canAdministerWorkspace;
  final String? initialRecommendationId;
  final ValueChanged<String>? onOpenRecommendationDeepLink;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncState = ref.watch(recommendationsControllerProvider);
    return asyncState.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (error, _) => MarkoAsyncErrorView(
        error: error,
        forbiddenResourceRu: 'ценовым рекомендациям',
        forbiddenResourceUk: 'цінових рекомендацій',
        onRetry: () => ref.invalidate(recommendationsControllerProvider),
      ),
      data: (state) {
        final recommendationId = initialRecommendationId;
        if (recommendationId != null &&
            state.deepLinkRequestedId != recommendationId) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            ref
                .read(recommendationsControllerProvider.notifier)
                .ensureVisible(recommendationId);
          });
        }
        return _RecommendationsContent(
          state: state,
          // A 401 raised by the run panel, the export or the deep link is the
          // same dead session the list would have met on its next request, and
          // every one of them is recorded here — including the controller's
          // own, which sets [RecommendationsState.sessionExpired] through the
          // same classifier. Reading the coordinator instead of the local flag
          // is what lets the notice come down again: only the coordinator sees
          // the dead credential actually being dropped.
          sessionExpired: ref.watch(markoSessionExpiredProvider),
          initialRecommendationId: recommendationId,
          canAdministerWorkspace: canAdministerWorkspace,
          onOpenRecommendationDeepLink: onOpenRecommendationDeepLink,
          onOpenCatalog: onOpenCatalog,
          onRefresh: () =>
              ref.read(recommendationsControllerProvider.notifier).refresh(),
          onShowLatestRun: () => ref
              .read(recommendationsControllerProvider.notifier)
              .showLatestRun(),
          onQueue: (queue) => ref
              .read(recommendationsControllerProvider.notifier)
              .setQueue(queue),
          onSort: (sort) => ref
              .read(recommendationsControllerProvider.notifier)
              .setSort(sort),
          onLoadMore: () =>
              ref.read(recommendationsControllerProvider.notifier).loadMore(),
        );
      },
    );
  }
}

class _RecommendationsContent extends StatelessWidget {
  const _RecommendationsContent({
    required this.state,
    required this.sessionExpired,
    required this.initialRecommendationId,
    required this.canAdministerWorkspace,
    required this.onOpenRecommendationDeepLink,
    required this.onOpenCatalog,
    required this.onRefresh,
    required this.onShowLatestRun,
    required this.onQueue,
    required this.onSort,
    required this.onLoadMore,
  });

  final RecommendationsState state;
  final bool sessionExpired;
  final String? initialRecommendationId;
  final bool canAdministerWorkspace;
  final ValueChanged<String>? onOpenRecommendationDeepLink;
  final VoidCallback? onOpenCatalog;
  final VoidCallback onRefresh;
  final VoidCallback onShowLatestRun;
  final ValueChanged<String> onQueue;
  final ValueChanged<String> onSort;
  final VoidCallback onLoadMore;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final recommendations = state.page.items;
    final actionCounts = state.page.actionCounts;
    return MarkoSessionExpiryAnswered(
      child: RefreshIndicator(
        onRefresh: () async => onRefresh(),
        child: _body(context, colors, recommendations, actionCounts),
      ),
    );
  }

  Widget _body(
    BuildContext context,
    MarkoTheme colors,
    List<PricingRecommendation> recommendations,
    RecommendationActionCounts actionCounts,
  ) {
    return ListView(
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
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        RecommendationExportButton(
                          queue: state.queue,
                          sort: state.sort,
                          action: state.actionFilter,
                          // The file must be the calculation on screen, not
                          // whichever run happens to be newest when the
                          // download is requested.
                          runId: state.runId,
                        ),
                        IconButton.outlined(
                          tooltip: context.localized(
                            ru: 'Обновить',
                            uk: 'Оновити',
                          ),
                          // Repeating the request with a token the backend
                          // already rejected can only fail again.
                          onPressed: sessionExpired ? null : onRefresh,
                          icon: const Icon(Icons.refresh_rounded),
                        ),
                      ],
                    ),
                  ],
                ),
                const SizedBox(height: 22),
                PricingRunPanel(
                  canAdministerWorkspace: canAdministerWorkspace,
                  // A finished run is a new calculation, so this is the one
                  // place that deliberately leaves the pinned run behind.
                  onRunFinished: onShowLatestRun,
                ),
                const SizedBox(height: 18),
                const DiscoveryFunnelPanel(),
                const SizedBox(height: 18),
                // The same answer the full-page error view gives, for a
                // session that died after the rows had already arrived.
                if (sessionExpired) ...[
                  const MarkoSessionExpiredMessage(
                    key: ValueKey('recommendations-session-expired'),
                  ),
                  const SizedBox(height: 16),
                ],
                if (state.error != null) ...[
                  MarkoInlineMessage(
                    message: state.error!,
                    tone: MarkoMessageTone.error,
                  ),
                  const SizedBox(height: 16),
                ],
                if (state.newerRunAvailable) ...[
                  MarkoInlineMessage(
                    key: const ValueKey('recommendations-newer-run'),
                    message: context.localized(
                      ru: 'Появился более новый расчёт. Показанные позиции относятся к предыдущему — их нельзя смешивать в одном списке.',
                      uk: 'З’явився новіший розрахунок. Показані позиції належать до попереднього — їх не можна змішувати в одному списку.',
                    ),
                    tone: MarkoMessageTone.warning,
                    action: TextButton(
                      onPressed: onShowLatestRun,
                      child: Text(
                        context.localized(
                          ru: 'Открыть новый расчёт',
                          uk: 'Відкрити новий розрахунок',
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                ],
                if (state.deepLinkUnavailable) ...[
                  MarkoInlineMessage(
                    message: context.localized(
                      ru: 'Не удалось открыть рекомендацию по ссылке. Она недоступна в этой рабочей области или больше не существует.',
                      uk: 'Не вдалося відкрити рекомендацію за посиланням. Вона недоступна в цій робочій області або більше не існує.',
                    ),
                    tone: MarkoMessageTone.warning,
                  ),
                  const SizedBox(height: 16),
                ],
                _SummaryRow(
                  // The run's population, not the active tab's: the tiles are
                  // how the operator learns which tab holds the work.
                  total: actionCounts.total,
                  raiseCount: actionCounts.raise,
                  lowerCount: actionCounts.lower,
                  reviewCount: actionCounts.review,
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
                  _EmptyRecommendations(
                    onOpenCatalog: onOpenCatalog,
                    counts: actionCounts,
                    queue: state.queue,
                    onShowEverything: () => onQueue('all'),
                    onShowReview: () => onQueue('review'),
                  )
                else
                  ...recommendations.map(
                    (recommendation) => Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: _RecommendationCard(
                        recommendation: recommendation,
                        canAdministerWorkspace: canAdministerWorkspace,
                        initiallyExpanded:
                            recommendation.id == initialRecommendationId,
                        onOpenDeepLink: onOpenRecommendationDeepLink,
                      ),
                    ),
                  ),
                if (recommendations.isNotEmpty && state.page.hasMore)
                  Center(
                    child: OutlinedButton.icon(
                      onPressed: state.isLoadingMore || sessionExpired
                          ? null
                          : onLoadMore,
                      icon: state.isLoadingMore
                          ? const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.expand_more_rounded),
                      label: Text(
                        context.localized(
                          ru: 'Показать ещё (${recommendations.length} из ${state.page.total})',
                          uk: 'Показати ще (${recommendations.length} із ${state.page.total})',
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ],
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
        label: context.localized(
          ru: 'Макс. изменение цены',
          uk: 'Макс. зміна ціни',
        ),
        icon: Icons.swap_vert_rounded,
      ),
      MarkoMenuEntry(
        value: 'PERCENT_RECOMMENDED_CHANGE',
        label: context.localized(
          ru: 'Макс. изменение, %',
          uk: 'Макс. зміна, %',
        ),
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
                    style: Theme.of(
                      context,
                    ).textTheme.labelSmall?.copyWith(color: colors.muted),
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
              label: context.localized(
                ru: 'Позиций в расчёте',
                uk: 'Позицій у розрахунку',
              ),
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
  const _RecommendationCard({
    required this.recommendation,
    required this.canAdministerWorkspace,
    required this.initiallyExpanded,
    required this.onOpenDeepLink,
  });

  final PricingRecommendation recommendation;
  final bool canAdministerWorkspace;
  final bool initiallyExpanded;
  final ValueChanged<String>? onOpenDeepLink;

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
  void initState() {
    super.initState();
    if (widget.initiallyExpanded) _evidence = _loadEvidence();
  }

  @override
  Widget build(BuildContext context) {
    final recommendation = widget.recommendation;
    final colors = MarkoTheme.of(context);
    // Каждая кнопка ниже — аутентифицированный запрос. После признанной
    // истёкшей сессии любая из них может только повторить тот же 401, поэтому
    // предлагать их — значит предлагать ошибку вместо входа.
    final sessionExpired = ref.watch(markoSessionExpiredProvider);
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
        initiallyExpanded: widget.initiallyExpanded,
        onExpansionChanged: (expanded) {
          if (expanded && _evidence == null) _refreshEvidence();
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
        title: LayoutBuilder(
          builder: (context, constraints) {
            final badge = _ActionBadge(
              label: _actionLabel(context, recommendation.action),
              foreground: foreground,
              background: background,
            );
            final compact =
                constraints.maxWidth < 360 ||
                MediaQuery.textScalerOf(context).scale(14) >= 18;
            if (compact) {
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    recommendation.name,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 6),
                  Align(alignment: Alignment.centerLeft, child: badge),
                ],
              );
            }
            return Row(
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
                badge,
              ],
            );
          },
        ),
        subtitle: Padding(
          padding: const EdgeInsets.only(top: 7),
          child: Wrap(
            spacing: 14,
            runSpacing: 5,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text(
                _identityLabel(recommendation),
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
          if (recommendation.hasAdvisoryPrice) ...[
            const SizedBox(height: 16),
            CustomerPriceAdvisory(recommendation: recommendation),
          ],
          const SizedBox(height: 16),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              OutlinedButton.icon(
                onPressed: widget.canAdministerWorkspace && !sessionExpired
                    ? _editContext
                    : null,
                icon: const Icon(Icons.inventory_2_outlined, size: 18),
                label: Text(
                  context.localized(
                    ru: 'Контекст склада',
                    uk: 'Контекст складу',
                  ),
                ),
              ),
              OutlinedButton.icon(
                onPressed: _verifyingReplay || sessionExpired
                    ? null
                    : _verifyReplay,
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
                  onPressed: _savingDecision || sessionExpired
                      ? null
                      : () => _recordDecision('accepted'),
                  icon: const Icon(Icons.check_rounded, size: 18),
                  label: Text(context.localized(ru: 'Принять', uk: 'Прийняти')),
                ),
              ],
              OutlinedButton.icon(
                onPressed: _savingDecision || sessionExpired
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
                onPressed: _savingDecision || sessionExpired
                    ? null
                    : () => _recordDecision('rejected'),
                child: Text(
                  context.localized(ru: 'Отклонить', uk: 'Відхилити'),
                ),
              ),
              if (widget.onOpenDeepLink != null)
                OutlinedButton.icon(
                  onPressed: () => widget.onOpenDeepLink!(recommendation.id),
                  icon: const Icon(Icons.link_rounded, size: 18),
                  label: Text(
                    context.localized(
                      ru: 'Постоянная ссылка',
                      uk: 'Постійне посилання',
                    ),
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
              marketMinimum: recommendation.advisoryMarketMinimum,
              targetBandLow:
                  recommendation.advisoryTargetBandLow ??
                  recommendation.lowerBound,
              targetBandHigh:
                  recommendation.advisoryTargetBandHigh ??
                  recommendation.upperBound,
              onOverride: widget.canAdministerWorkspace && !sessionExpired
                  ? _overrideTier
                  : null,
              onComparabilityFeedback:
                  widget.canAdministerWorkspace && !sessionExpired
                  ? _recordComparabilityFeedback
                  : null,
              onComparabilityReview:
                  widget.canAdministerWorkspace && !sessionExpired
                  ? _rerunComparabilityReview
                  : null,
            ),
            const SizedBox(height: 18),
            const Divider(),
            const SizedBox(height: 14),
            FitmentCandidatesPanel(
              catalogItemId: recommendation.catalogItemId,
              canAdministerWorkspace: widget.canAdministerWorkspace,
            ),
          ],
        ],
      ),
    );
  }

  String _identityLabel(PricingRecommendation recommendation) {
    final identity = <String>[];
    if (recommendation.oe.trim().isNotEmpty) {
      identity.add('OE ${recommendation.oe}');
    } else if (recommendation.mpn?.trim().isNotEmpty ?? false) {
      identity.add('MPN ${recommendation.mpn}');
    } else if (recommendation.searchIdentity?.trim().isNotEmpty ?? false) {
      identity.add('Поиск ${recommendation.searchIdentity}');
    }
    final suffix = identity.isEmpty ? '' : ' · ${identity.join(' · ')}';
    return 'SKU ${recommendation.sku}$suffix';
  }

  String _priceDecision(BuildContext context, PricingRecommendation item) {
    final advisory = item.recommendedPrice == null && item.hasAdvisoryPrice;
    final target = item.recommendedPrice ?? item.advisoryRecommendedPrice;
    if (target == null && !item.automaticEligible) {
      return context.localized(
        ru: '${_recommendationMoney(item, item.currentPrice)} — автоцена не сформирована',
        uk: '${_recommendationMoney(item, item.currentPrice)} — автоціну не сформовано',
      );
    }
    if (target == null) {
      return context.localized(
        ru: '${_recommendationMoney(item, item.currentPrice)} — без изменений',
        uk: '${_recommendationMoney(item, item.currentPrice)} — без змін',
      );
    }
    final change =
        item.absoluteRecommendedChange ?? (target - item.currentPrice).abs();
    final percent =
        item.percentageRecommendedChange ??
        (item.currentPrice.isZero ? 0 : change.ratioTo(item.currentPrice));
    final sign = target >= item.currentPrice ? '+' : '−';
    final suffix = advisory
        ? context.localized(
            ru: ' · ориентир, требует проверки',
            uk: ' · орієнтир, потребує перевірки',
          )
        : '';
    return '${_recommendationMoney(item, item.currentPrice)} → '
        '${_recommendationMoney(item, target)} · '
        '$sign${_recommendationMoney(item, change)} '
        '(${(percent * 100).toStringAsFixed(1)}%)$suffix';
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
      // Истёкшая сессия — не «replay недоступен»: воспроизведение расчёта
      // никуда не делось, доступа к нему нет. Страница отвечает на это одним
      // предложением и одной кнопкой, а снекбар с английской строкой бэкенда
      // уехал бы через четыре секунды, ничего не предложив.
      if (ref.classifySessionExpiry(error)) return;
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
      _refreshEvidence();
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
      if (ref.classifySessionExpiry(error)) return;
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

  Future<void> _recordComparabilityFeedback(
    RecommendationEvidence evidence,
  ) async {
    final review = evidence.llmReview;
    if (review == null) return;
    final values = await showComparabilityFeedbackDialog(
      context,
      review: review,
    );
    if (values == null || !mounted) return;
    try {
      await ref
          .read(pricingApiProvider)
          .recordComparabilityFeedback(review.reviewId, values);
      if (!mounted) return;
      _refreshEvidence();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            context.localized(
              ru:
                  'Разметка сохранена. Она станет эталоном и будет учтена '
                  'в следующем расчёте.',
              uk:
                  'Розмітку збережено. Вона стане еталоном і буде врахована '
                  'в наступному розрахунку.',
            ),
          ),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      _showEvidenceError(error);
    }
  }

  Future<void> _rerunComparabilityReview(
    RecommendationEvidence evidence,
  ) async {
    try {
      await ref
          .read(pricingApiProvider)
          .reviewComparability(evidence.observationId, force: true);
      if (!mounted) return;
      _refreshEvidence();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            context.localized(
              ru:
                  'Новая проверка сохранена. Текущая рекомендация не '
                  'переписана; результат войдёт в следующий расчёт.',
              uk:
                  'Нову перевірку збережено. Поточну рекомендацію не '
                  'перезаписано; результат увійде до наступного розрахунку.',
            ),
          ),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      _showEvidenceError(error);
    }
  }

  void _refreshEvidence() {
    setState(() => _evidence = _loadEvidence());
  }

  /// Доказательства грузятся через ту же классификацию, что и всё остальное.
  ///
  /// [FutureBuilder] не может поднять состояние приложения из `build`, поэтому
  /// 401 признаётся здесь — там, где он приходит. Ошибка при этом не
  /// проглатывается: список сам решает, что показать вместо строки бэкенда.
  Future<List<RecommendationEvidence>> _loadEvidence() async {
    try {
      return await ref
          .read(pricingApiProvider)
          .getEvidence(widget.recommendation.id);
    } catch (error) {
      if (mounted) ref.classifySessionExpiry(error);
      rethrow;
    }
  }

  void _showEvidenceError(Object error) {
    if (ref.classifySessionExpiry(error)) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          context.localized(
            ru: 'Не удалось сохранить проверку: $error',
            uk: 'Не вдалося зберегти перевірку: $error',
          ),
        ),
      ),
    );
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
    required this.marketMinimum,
    required this.targetBandLow,
    required this.targetBandHigh,
    required this.onOverride,
    required this.onComparabilityFeedback,
    required this.onComparabilityReview,
  });

  final Future<List<RecommendationEvidence>> future;
  final Map<String, Map<String, dynamic>> normalizedOffers;
  final DecimalValue? marketMinimum;
  final DecimalValue? targetBandLow;
  final DecimalValue? targetBandHigh;
  final Future<void> Function(RecommendationEvidence)? onOverride;
  final Future<void> Function(RecommendationEvidence)? onComparabilityFeedback;
  final Future<void> Function(RecommendationEvidence)? onComparabilityReview;

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
          // Доказательства не «не загрузились» — их не отдали мёртвому токену.
          // Единственный ответ на это уже есть на странице, и повторять его
          // здесь означало бы рассказать про две разные беды.
          final expired = markoIsSessionExpired(snapshot.error);
          if (expired && MarkoSessionExpiryAnswered.above(context)) {
            return Text(
              context.localized(
                ru: 'Доказательства откроются после повторного входа.',
                uk: 'Докази відкриються після повторного входу.',
              ),
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: colors.muted),
            );
          }
          if (expired) return const MarkoSessionExpiredMessage();
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
                  DecimalValue.tryParse(normalized?['normalized_price']) ??
                  item.normalizedPrice;
              final multiplier =
                  double.tryParse(
                    normalized?['multiplier']?.toString() ?? '',
                  ) ??
                  item.multiplier;
              final pricingAdmitted =
                  item.llmReview?.pricingAdmission == 'ADMITTED';
              final coefficientLine = !pricingAdmitted
                  ? context.localized(
                      ru: 'Цена скрыта до ADMITTED',
                      uk: 'Ціну приховано до ADMITTED',
                    )
                  : normalizedPrice != null && multiplier != null
                  ? context.localized(
                      ru:
                          'KEMP-эквивалент: ${_money(normalizedPrice, currency: item.currency)} · '
                          'm=${multiplier.toStringAsFixed(2)}',
                      uk:
                          'KEMP-еквівалент: ${_money(normalizedPrice, currency: item.currency)} · '
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
                                      ru: 'Детерминированная проверка: пройдена',
                                      uk: 'Детермінована перевірка: пройдена',
                                    )
                                  : context.localized(
                                      ru: 'Детерминированная проверка: нужна ручная проверка',
                                      uk: 'Детермінована перевірка: потрібна ручна перевірка',
                                    ),
                              style: Theme.of(context).textTheme.bodySmall
                                  ?.copyWith(
                                    color: item.automaticEligible
                                        ? colors.positive
                                        : colors.warning,
                                  ),
                            ),
                            const SizedBox(height: 5),
                            RecommendationEvidenceDetails(evidence: item),
                            ComparabilityReviewPanel(
                              evidence: item,
                              normalizedPrice: normalizedPrice,
                              marketMinimum: marketMinimum,
                              targetBandLow: targetBandLow,
                              targetBandHigh: targetBandHigh,
                              onFeedback: onComparabilityFeedback,
                              onReview: onComparabilityReview,
                            ),
                          ],
                        ),
                      ),
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          if (pricingAdmitted)
                            Text(
                              _money(item.price, currency: item.currency),
                              style: Theme.of(context).textTheme.titleMedium,
                            )
                          else
                            Text(
                              context.localized(
                                ru: 'Цена после ADMITTED',
                                uk: 'Ціна після ADMITTED',
                              ),
                              style: Theme.of(context).textTheme.bodySmall,
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
                      if (onOverride != null)
                        IconButton(
                          tooltip: context.localized(
                            ru: 'Уточнить tier',
                            uk: 'Уточнити tier',
                          ),
                          onPressed: () => onOverride!(item),
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

class RecommendationEvidenceDetails extends StatelessWidget {
  const RecommendationEvidenceDetails({required this.evidence, super.key});

  final RecommendationEvidence evidence;

  @override
  Widget build(BuildContext context) {
    final style = Theme.of(context).textTheme.bodySmall;
    final extracted = evidence.extractedOeNorms.isEmpty
        ? '—'
        : evidence.extractedOeNorms.join(', ');
    final calibrationExclusions = evidence.calibrationExclusionCodes.isEmpty
        ? '—'
        : evidence.calibrationExclusionCodes.join(', ');
    final reenriched = evidence.oeReenrichedAt == null
        ? '—'
        : formatLocalDateTime(evidence.oeReenrichedAt!);
    final availability = switch (evidence.isAvailable) {
      true => context.localized(ru: 'в наличии', uk: 'у наявності'),
      false => context.localized(ru: 'нет в наличии', uk: 'немає в наявності'),
      null => context.localized(ru: 'неизвестно', uk: 'невідомо'),
    };

    return DecoratedBox(
      decoration: BoxDecoration(
        color: MarkoTheme.of(context).surfaceMuted.withValues(alpha: 0.72),
        borderRadius: BorderRadius.circular(7),
      ),
      child: Padding(
        padding: const EdgeInsets.all(8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'OE: status=${evidence.oeVerificationStatus} · '
              'search=${_emptyAsDash(evidence.searchOeNorm)} · '
              'extracted=$extracted · '
              'verified=${evidence.verifiedMatchedOeNorm ?? '—'} · '
              'identity=${evidence.comparisonIdentityKey ?? '—'}',
              style: style,
            ),
            Text(
              '${context.localized(ru: 'Provenance', uk: 'Походження')}: '
              'seller=${_emptyAsDash(evidence.sellerId)} · '
              'OE extractor=${_emptyAsDash(evidence.oeExtractorVersion)} · '
              'source method=${_emptyAsDash(evidence.sourceConfidenceMethodVersion)} · '
              're-enriched=$reenriched · '
              'error=${evidence.oeReenrichmentErrorCode ?? '—'}',
              style: style,
            ),
            Text(
              'OE evidence: ${_safeJson(evidence.oeEvidenceSummary)}',
              style: style,
            ),
            Text(
              '${context.localized(ru: 'Флаги', uk: 'Прапорці')}: '
              '$availability · used=${evidence.isUsed} · '
              'KEMP=${evidence.isKemp} · owned=${evidence.isOwned}',
              style: style,
            ),
            Text(
              'Hard gate: ${evidence.comparabilityHardGateResult} · '
              'calibration exclusions=$calibrationExclusions',
              style: style,
            ),
            Text(
              'Source factors: ${_safeJson(evidence.sourceConfidenceFactors)} · '
              'outcomes=${_safeJson(evidence.offerOutcomeCounts)}',
              style: style,
            ),
            Text(
              'Policy: id=${evidence.comparabilityPolicyId ?? '—'} · '
              'hash=${evidence.comparabilityPolicyHash ?? '—'}',
              style: style,
            ),
          ],
        ),
      ),
    );
  }
}

String _emptyAsDash(String value) => value.trim().isEmpty ? '—' : value;

String _safeJson(Object value) {
  try {
    return jsonEncode(value);
  } on Object {
    return '<unavailable>';
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

class CustomerPriceAdvisory extends StatelessWidget {
  const CustomerPriceAdvisory({super.key, required this.recommendation});

  final PricingRecommendation recommendation;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final target = recommendation.advisoryRecommendedPrice!;
    final marketMinimum = recommendation.advisoryMarketMinimum;
    final bandLow = recommendation.advisoryTargetBandLow;
    final bandHigh = recommendation.advisoryTargetBandHigh;
    final excludedImplausible = recommendation.customerExcludedImplausibleCount;
    final plausibilityFloor = recommendation.customerPlausibilityFloor;
    final direction = recommendation.advisoryAction == 'LOWER'
        ? context.localized(ru: 'Снизить', uk: 'Знизити')
        : context.localized(ru: 'Поднять', uk: 'Підвищити');
    return Container(
      key: const ValueKey('customer-price-advisory'),
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: colors.tertiaryContainer.withValues(alpha: 0.42),
        border: Border.all(color: colors.tertiary.withValues(alpha: 0.35)),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            context.localized(
              ru: 'Ценовой ориентир заказчика',
              uk: 'Ціновий орієнтир замовника',
            ),
            style: Theme.of(context).textTheme.titleSmall?.copyWith(
              color: colors.onTertiaryContainer,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            '$direction: ${_recommendationMoney(recommendation, target)}',
            style: Theme.of(
              context,
            ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
          ),
          if (marketMinimum != null && bandLow != null && bandHigh != null) ...[
            const SizedBox(height: 4),
            Text(
              context.localized(
                ru:
                    'Минимальная сопоставимая цена: '
                    '${_recommendationMoney(recommendation, marketMinimum)}. '
                    'Допустимый коридор: '
                    '${_recommendationMoney(recommendation, bandLow)} — '
                    '${_recommendationMoney(recommendation, bandHigh)}.',
                uk:
                    'Мінімальна зіставна ціна: '
                    '${_recommendationMoney(recommendation, marketMinimum)}. '
                    'Допустимий коридор: '
                    '${_recommendationMoney(recommendation, bandLow)} — '
                    '${_recommendationMoney(recommendation, bandHigh)}.',
              ),
            ),
          ],
          if (excludedImplausible > 0 && plausibilityFloor != null) ...[
            const SizedBox(height: 4),
            Text(
              context.localized(
                ru:
                    'Из ценовой цели исключено подозрительно дешёвых '
                    'предложений: $excludedImplausible (ниже '
                    '${_recommendationMoney(recommendation, plausibilityFloor)}). '
                    'Они остаются в доказательствах.',
                uk:
                    'Із цінової цілі виключено підозріло дешевих '
                    'пропозицій: $excludedImplausible (нижче '
                    '${_recommendationMoney(recommendation, plausibilityFloor)}). '
                    'Вони залишаються в доказах.',
              ),
            ),
          ],
          const SizedBox(height: 6),
          Text(
            context.localized(
              ru:
                  'Брендовый уровень, закупка и возраст остатка в цене не '
                  'участвуют. Сопоставимость требует проверки; цена '
                  'автоматически не применяется.',
              uk:
                  'Рівень бренду, закупівля та вік залишку в ціні не '
                  'враховуються. Зіставність потребує перевірки; ціна '
                  'автоматично не застосовується.',
            ),
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

class _Evidence extends StatelessWidget {
  const _Evidence({required this.recommendation});

  final PricingRecommendation recommendation;

  @override
  Widget build(BuildContext context) {
    final budgetFloor =
        recommendation.customerPricingPolicy?['strategy'] == 'budget_floor';
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
            ru: budgetFloor
                ? 'Минимальная сопоставимая цена'
                : 'Справедливая цена',
            uk: budgetFloor ? 'Мінімальна зіставна ціна' : 'Справедлива ціна',
          ),
          value: recommendation.fairPrice == null
              ? context.localized(ru: 'не рассчитана', uk: 'не розрахована')
              : _recommendationMoney(recommendation, recommendation.fairPrice!),
        ),
        _KeyValue(
          label: context.localized(
            ru: budgetFloor ? 'Целевой коридор (−5%…−2%)' : 'Рыночный диапазон',
            uk: budgetFloor
                ? 'Цільовий коридор (−5%…−2%)'
                : 'Ринковий діапазон',
          ),
          value: recommendation.lowerBound == null
              ? '—'
              : '${_recommendationMoney(recommendation, recommendation.lowerBound!)} — '
                    '${_recommendationMoney(recommendation, recommendation.upperBound!)}',
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
              ru: budgetFloor ? 'Основа расчёта' : 'Робастная модель',
              uk: budgetFloor ? 'Основа розрахунку' : 'Робастна модель',
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
          Expanded(
            child: Text(
              value,
              textAlign: TextAlign.end,
              softWrap: true,
              style: Theme.of(context).textTheme.bodyMedium,
            ),
          ),
        ],
      ),
    );
  }
}

/// Empty list, explained.
///
/// An empty list has two very different causes and the operator has to be able
/// to tell them apart: the run produced nothing, or the selected tab happens to
/// be empty while the work sits under another one. Telling the second case to
/// "connect your stores" sends the operator to fix something that is not broken.
class _EmptyRecommendations extends StatelessWidget {
  const _EmptyRecommendations({
    required this.onOpenCatalog,
    required this.counts,
    required this.queue,
    required this.onShowEverything,
    required this.onShowReview,
  });

  final VoidCallback? onOpenCatalog;
  final RecommendationActionCounts counts;
  final String queue;
  final VoidCallback onShowEverything;
  final VoidCallback onShowReview;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final hiddenByFilter = counts.total > 0 && queue != 'all';
    return MarkoPanel(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 40),
      child: Column(
        children: [
          Icon(
            hiddenByFilter
                ? Icons.filter_alt_off_rounded
                : Icons.price_check_rounded,
            size: 38,
            color: colors.brand,
          ),
          const SizedBox(height: 14),
          Text(
            hiddenByFilter
                ? context.localized(
                    ru: 'В этой вкладке пусто',
                    uk: 'У цій вкладці порожньо',
                  )
                : context.localized(
                    ru: 'Пока нет рекомендаций',
                    uk: 'Рекомендацій поки немає',
                  ),
            style: Theme.of(context).textTheme.titleLarge,
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 7),
          Text(
            hiddenByFilter
                ? context.localized(
                    ru: 'В расчёте есть позиции (${counts.total}), но ни одна не попала в эту вкладку.',
                    uk: 'У розрахунку є позиції (${counts.total}), але жодна не потрапила до цієї вкладки.',
                  )
                : context.localized(
                    ru: 'Запустите расчёт по нужному импорту каталога в блоке выше.',
                    uk: 'Запустіть розрахунок за потрібним імпортом каталогу в блоці вище.',
                  ),
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodyMedium,
          ),
          const SizedBox(height: 18),
          if (hiddenByFilter)
            Wrap(
              spacing: 10,
              runSpacing: 10,
              alignment: WrapAlignment.center,
              children: [
                FilledButton.icon(
                  onPressed: onShowEverything,
                  icon: const Icon(Icons.list_rounded, size: 18),
                  label: Text(
                    context.localized(
                      ru: 'Показать все (${counts.total})',
                      uk: 'Показати всі (${counts.total})',
                    ),
                  ),
                ),
                if (counts.review > 0 && queue != 'review')
                  OutlinedButton.icon(
                    onPressed: onShowReview,
                    icon: const Icon(Icons.fact_check_outlined, size: 18),
                    label: Text(
                      context.localized(
                        ru: 'Проверить вручную (${counts.review})',
                        uk: 'Перевірити вручну (${counts.review})',
                      ),
                    ),
                  ),
              ],
            )
          else if (onOpenCatalog != null)
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
      ),
    );
  }
}

String _money(Object value, {required String currency}) =>
    formatMoney(value, currency: currency);

String _recommendationMoney(
  PricingRecommendation recommendation,
  DecimalValue value,
) => formatMoney(
  value,
  currency: recommendation.currency,
  priceTick: recommendation.priceTick,
  fractionDigits: recommendation.priceTickScale,
);

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
    ru: '${_recommendationMoney(recommendation, recommendation.priorityScore)}/мес. с учётом confidence',
    uk: '${_recommendationMoney(recommendation, recommendation.priorityScore)}/міс. з урахуванням confidence',
  ),
  'clearance_priority' => context.localized(
    ru: '${_recommendationMoney(recommendation, recommendation.priorityScore)} замороженного капитала',
    uk: '${_recommendationMoney(recommendation, recommendation.priorityScore)} замороженого капіталу',
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
  return summarizeLimited(
    recommendation.reasonCodes.map((code) => _reasonLabel(context, code)),
    limit: 2,
    separator: ' · ',
    overflowLabel: (hidden) =>
        context.localized(ru: 'и ещё $hidden', uk: 'і ще $hidden'),
  );
}

String _reasonLabel(BuildContext context, String code) =>
    pricingReasonLabel(context, code);

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
  return summarizeLimited(
    entries.map(
      (entry) => '${_reasonLabel(context, entry.key)}: ${entry.value}',
    ),
    limit: 4,
    separator: ' · ',
    overflowLabel: (hidden) =>
        context.localized(ru: 'и ещё $hidden', uk: 'і ще $hidden'),
  );
}
