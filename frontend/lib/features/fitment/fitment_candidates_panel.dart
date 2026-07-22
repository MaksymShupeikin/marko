import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/app_theme.dart';
import 'fitment_candidate_tile.dart';
import 'fitment_controller.dart';
import 'fitment_recommendation_card.dart';

class FitmentCandidatesPanel extends ConsumerWidget {
  const FitmentCandidatesPanel({required this.catalogItemId, super.key});

  final String catalogItemId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = MarkoTheme.of(context);
    final provider = fitmentControllerProvider(catalogItemId);
    final asyncState = ref.watch(provider);
    return asyncState.when(
      loading: () => const LinearProgressIndicator(),
      error: (error, _) => Text(
        'Fitment intelligence недоступен: $error',
        style: Theme.of(
          context,
        ).textTheme.bodySmall?.copyWith(color: colors.negative),
      ),
      data: (state) {
        final page = state.bundle.page;
        final recommendation = state.bundle.recommendation;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (state.error != null)
              _Notice(
                text: state.error!,
                color: colors.negative,
                onClose: () => ref.read(provider.notifier).clearNotice(),
              ),
            if (state.message != null)
              _Notice(
                text: state.message!,
                color: colors.positive,
                onClose: () => ref.read(provider.notifier).clearNotice(),
              ),
            Row(
              children: [
                Expanded(
                  child: Text(
                    'Проверка применимости · ${page.total}',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                IconButton(
                  tooltip: 'Обновить fitment evidence',
                  onPressed: state.isSubmitting
                      ? null
                      : () => ref.read(provider.notifier).reload(),
                  icon: const Icon(Icons.refresh_rounded, size: 18),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              'Compatibility и price comparability разделены. Даже принятая рекомендация не публикует цену.',
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: colors.muted),
            ),
            const SizedBox(height: 10),
            if (page.analysisId == null)
              Text(
                'Fitment-анализ ещё не запускался. Рыночные карточки не считаются доказанными аналогами.',
                style: Theme.of(
                  context,
                ).textTheme.bodySmall?.copyWith(color: colors.warning),
              )
            else ...[
              if (recommendation == null)
                Align(
                  alignment: Alignment.centerLeft,
                  child: FilledButton.icon(
                    onPressed: state.isSubmitting
                        ? null
                        : () => ref
                              .read(provider.notifier)
                              .generateRecommendation(),
                    icon: const Icon(Icons.calculate_outlined, size: 18),
                    label: const Text('Рассчитать совет'),
                  ),
                )
              else
                FitmentRecommendationCard(
                  recommendation: recommendation,
                  isSubmitting: state.isSubmitting,
                  onReview:
                      ({
                        required operation,
                        required reasonCode,
                        approvedPrice,
                        comment,
                        allowBelowFloor = false,
                        belowFloorWarningConfirmed = false,
                      }) => ref
                          .read(provider.notifier)
                          .reviewRecommendation(
                            recommendation,
                            operation: operation,
                            reasonCode: reasonCode,
                            approvedPrice: approvedPrice,
                            comment: comment,
                            allowBelowFloor: allowBelowFloor,
                            belowFloorWarningConfirmed:
                                belowFloorWarningConfirmed,
                          ),
                ),
              ...page.items.map(
                (candidate) => FitmentCandidateTile(
                  candidate: candidate,
                  isSubmitting: state.isSubmitting,
                  onReview:
                      ({
                        required decision,
                        required reasonCode,
                        comment,
                        evidenceVerdicts = const {},
                      }) => ref
                          .read(provider.notifier)
                          .reviewCandidate(
                            candidate,
                            decision: decision,
                            reasonCode: reasonCode,
                            comment: comment,
                            evidenceVerdicts: evidenceVerdicts,
                          ),
                  onSellerReview: ({required relation, required reason}) => ref
                      .read(provider.notifier)
                      .markSeller(
                        candidate,
                        relation: relation,
                        reason: reason,
                      ),
                ),
              ),
            ],
          ],
        );
      },
    );
  }
}

class _Notice extends StatelessWidget {
  const _Notice({
    required this.text,
    required this.color,
    required this.onClose,
  });

  final String text;
  final Color color;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(7),
      ),
      child: Row(
        children: [
          Expanded(child: Text(text)),
          IconButton(
            visualDensity: VisualDensity.compact,
            onPressed: onClose,
            icon: const Icon(Icons.close_rounded, size: 16),
          ),
        ],
      ),
    );
  }
}
