part of '../recommendations_page.dart';

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
