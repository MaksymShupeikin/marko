part of '../recommendations_page.dart';

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
