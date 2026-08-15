part of '../recommendations_page.dart';

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
            ru: budgetFloor ? 'Цель: минимум − 5%' : 'Рыночный диапазон',
            uk: budgetFloor ? 'Ціль: мінімум − 5%' : 'Ринковий діапазон',
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
