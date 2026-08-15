import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/api_client.dart';
import '../../core/app_language.dart';
import '../../core/app_theme.dart';
import '../../core/marko_motion.dart';
import '../../core/marko_ui.dart';
import '../../core/presentation_formatters.dart';
import '../../core/session_expiry.dart';
import '../../core/widgets/marko_menu.dart';
import '../../core/widgets/marko_skeleton.dart';
import 'package:go_router/go_router.dart';
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

part 'widgets/recommendation_sort_selector.dart';
part 'widgets/recommendation_summary_row.dart';
part 'widgets/recommendation_queue_filters.dart';
part 'widgets/recommendation_card.dart';
part 'widgets/recommendation_replay_status.dart';
part 'widgets/recommendation_market_evidence.dart';
part 'widgets/recommendation_evidence_details.dart';
part 'widgets/recommendation_catalog_evidence.dart';
part 'widgets/recommendation_action_badge.dart';
part 'widgets/customer_price_advisory.dart';
part 'widgets/recommendation_evidence.dart';
part 'widgets/recommendation_data_health.dart';
part 'widgets/recommendation_empty.dart';
part 'widgets/recommendation_formatters.dart';
part 'widgets/recommendation_queue.dart';

class RecommendationsPage extends ConsumerWidget {
  const RecommendationsPage({
    this.onOpenCatalog,
    this.canAdministerWorkspace = false,
    this.initialRecommendationId,
    this.initialQueue,
    this.initialSort,
    this.initialAction,
    this.onOpenRecommendationDeepLink,
    super.key,
  });

  final VoidCallback? onOpenCatalog;
  final bool canAdministerWorkspace;
  final String? initialRecommendationId;
  final String? initialQueue;
  final String? initialSort;
  final String? initialAction;
  final ValueChanged<String>? onOpenRecommendationDeepLink;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncState = ref.watch(recommendationsControllerProvider);
    return asyncState.when(
      loading: () => const MarkoQueueSkeleton(),
      error: (error, _) => MarkoAsyncErrorView(
        error: error,
        forbiddenResourceRu: 'ценовым рекомендациям',
        forbiddenResourceUk: 'цінових рекомендацій',
        onRetry: () => ref.invalidate(recommendationsControllerProvider),
      ),
      data: (state) {
        final recommendationId = initialRecommendationId;
        WidgetsBinding.instance.addPostFrameCallback((_) {
          final notifier = ref.read(recommendationsControllerProvider.notifier);
          if (recommendationId != null &&
              state.deepLinkRequestedId != recommendationId) {
            notifier.ensureVisible(recommendationId);
          }
          if (initialQueue != null && initialQueue != state.queue) {
            notifier.setQueue(initialQueue!);
          }
          if (initialSort != null && initialSort != state.sort) {
            notifier.setSort(initialSort!);
          }
          if (initialAction != null && initialAction != state.actionFilter) {
            notifier.setActionFilter(initialAction);
          }
        });
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
          onQueue: (queue) {
            ref
                .read(recommendationsControllerProvider.notifier)
                .setQueue(queue);
            _replaceQuery(context, 'queue', queue);
          },
          onSort: (sort) {
            ref.read(recommendationsControllerProvider.notifier).setSort(sort);
            _replaceQuery(context, 'sort', sort);
          },
          onLoadMore: () =>
              ref.read(recommendationsControllerProvider.notifier).loadMore(),
        );
      },
    );
  }
}

void _replaceQuery(BuildContext context, String key, String value) {
  final router = GoRouter.maybeOf(context);
  if (router == null) return;
  final uri = GoRouterState.of(context).uri;
  final next = Map<String, String>.from(uri.queryParameters)..[key] = value;
  router.go(uri.replace(queryParameters: next).toString());
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
                MarkoFadeUp(
                  child: Wrap(
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
                  _RecommendationQueue(
                    state: state,
                    canAdministerWorkspace: canAdministerWorkspace,
                    sessionExpired: sessionExpired,
                    initialRecommendationId: initialRecommendationId,
                    onOpenDeepLink: onOpenRecommendationDeepLink,
                    onLoadMore: onLoadMore,
                  ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
