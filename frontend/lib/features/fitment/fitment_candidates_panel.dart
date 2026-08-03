import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/app_language.dart';
import '../../core/app_theme.dart';
import '../../core/marko_ui.dart';
import '../../core/session_expiry.dart';
import 'fitment_candidate_tile.dart';
import 'fitment_controller.dart';
import 'fitment_recommendation_card.dart';

class FitmentCandidatesPanel extends ConsumerWidget {
  const FitmentCandidatesPanel({
    required this.catalogItemId,
    this.canAdministerWorkspace = false,
    super.key,
  });

  final String catalogItemId;
  final bool canAdministerWorkspace;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = MarkoTheme.of(context);
    final provider = fitmentControllerProvider(catalogItemId);
    final asyncState = ref.watch(provider);
    // Мёртвый токен здесь ничем не отличается от мёртвого токена в списке
    // рекомендаций: ни одно действие панели после него не сработает.
    final sessionExpired = ref.watch(markoSessionExpiredProvider);
    return asyncState.when(
      loading: () => const LinearProgressIndicator(),
      error: (error, _) => _error(context, colors, error),
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
                  onPressed: state.isSubmitting || sessionExpired
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
                if (canAdministerWorkspace)
                  Align(
                    alignment: Alignment.centerLeft,
                    child: FilledButton.icon(
                      onPressed: state.isSubmitting || sessionExpired
                          ? null
                          : () => ref
                                .read(provider.notifier)
                                .generateRecommendation(),
                      icon: const Icon(Icons.calculate_outlined, size: 18),
                      label: const Text('Рассчитать совет'),
                    ),
                  )
                else
                  Text(
                    'Расчёт нового совета доступен владельцу или администратору.',
                    style: Theme.of(
                      context,
                    ).textTheme.bodySmall?.copyWith(color: colors.muted),
                  )
              else
                FitmentRecommendationCard(
                  recommendation: recommendation,
                  isSubmitting: state.isSubmitting || sessionExpired,
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
                  isSubmitting: state.isSubmitting || sessionExpired,
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
                  onSellerReview: canAdministerWorkspace
                      ? ({required relation, required reason}) => ref
                            .read(provider.notifier)
                            .markSeller(
                              candidate,
                              relation: relation,
                              reason: reason,
                            )
                      : null,
                ),
              ),
            ],
          ],
        );
      },
    );
  }

  /// Панель не может ответить за истёкшую сессию дважды: страница уже это
  /// сделала, и вторая копия того же предложения читается как вторая беда.
  Widget _error(BuildContext context, MarkoTheme colors, Object error) {
    if (markoIsSessionExpired(error)) {
      if (!MarkoSessionExpiryAnswered.above(context)) {
        return const MarkoSessionExpiredMessage(
          key: ValueKey('fitment-session-expired'),
        );
      }
      return Text(
        context.localized(
          ru: 'Проверка применимости откроется после повторного входа.',
          uk: 'Перевірка застосовності відкриється після повторного входу.',
        ),
        style: Theme.of(
          context,
        ).textTheme.bodySmall?.copyWith(color: colors.muted),
      );
    }
    return Text(
      'Fitment intelligence недоступен: $error',
      style: Theme.of(
        context,
      ).textTheme.bodySmall?.copyWith(color: colors.negative),
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
