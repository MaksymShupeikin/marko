import 'package:flutter/material.dart';

import '../../core/app_theme.dart';
import '../../core/presentation_formatters.dart';
import 'fitment_models.dart';

typedef RecommendationReviewCallback =
    Future<bool> Function({
      required String operation,
      required String reasonCode,
      double? approvedPrice,
      String? comment,
      bool allowBelowFloor,
      bool belowFloorWarningConfirmed,
    });

class FitmentRecommendationCard extends StatelessWidget {
  const FitmentRecommendationCard({
    required this.recommendation,
    required this.isSubmitting,
    required this.onReview,
    super.key,
  });

  final FitmentMarketRecommendation recommendation;
  final bool isSubmitting;
  final RecommendationReviewCallback onReview;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final suggested = recommendation.recommendedPrice;
    final actionColor = switch (recommendation.action) {
      'consider_raise' => colors.positive,
      'consider_reduce' => colors.warning,
      'hold' => colors.muted,
      _ => colors.warning,
    };
    return Container(
      margin: const EdgeInsets.only(bottom: 14),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: colors.surfaceMuted,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: actionColor.withValues(alpha: 0.45)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      recommendation.actionLabel,
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        color: actionColor,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      'Стратегия: ${recommendation.strategy} · confidence ${(recommendation.confidence * 100).toStringAsFixed(1)}%',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
              _PriceColumn(recommendation: recommendation),
            ],
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 12,
            runSpacing: 5,
            children: [
              Text(
                'n_eff ${recommendation.effectiveSampleSize.toStringAsFixed(2)}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              Text(
                'seller groups ${recommendation.independentSellerGroups}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              if (recommendation.marketAnchor != null)
                Text(
                  'anchor ${recommendation.marketAnchor!.toStringAsFixed(2)}',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              if (recommendation.approvedPriceFloor != null)
                Text(
                  'floor ${recommendation.approvedPriceFloor!.toStringAsFixed(2)}',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
            ],
          ),
          const SizedBox(height: 7),
          Text(
            _rangeText(recommendation),
            style: Theme.of(context).textTheme.bodySmall,
          ),
          if (recommendation.reasonCodes.isNotEmpty)
            Text(
              'Причины: ${summarizeLimited(recommendation.reasonCodes, limit: 4, separator: ', ', overflowLabel: (hidden) => 'и ещё $hidden')}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          if (recommendation.warnings.isNotEmpty)
            Text(
              'Предупреждения: ${recommendation.warnings.join(', ')}',
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: colors.warning),
            ),
          const SizedBox(height: 8),
          Row(
            children: [
              Icon(Icons.lock_person_outlined, size: 16, color: colors.muted),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  'Это совет: ни одна цена на Prom.ua не изменяется автоматически.',
                  style: Theme.of(
                    context,
                  ).textTheme.bodySmall?.copyWith(color: colors.muted),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 7,
            runSpacing: 7,
            children: [
              if (suggested != null)
                FilledButton(
                  onPressed: isSubmitting
                      ? null
                      : () => onReview(
                          operation: 'accept',
                          reasonCode: 'other',
                          comment: 'Принято без автопубликации',
                          allowBelowFloor: false,
                          belowFloorWarningConfirmed: false,
                        ),
                  child: const Text('Принять'),
                ),
              if (suggested != null)
                OutlinedButton(
                  onPressed: isSubmitting ? null : () => _changePrice(context),
                  child: const Text('Изменить цену'),
                ),
              OutlinedButton(
                onPressed: isSubmitting
                    ? null
                    : () => _reviewWithComment(context, 'reject'),
                child: const Text('Отклонить'),
              ),
              TextButton(
                onPressed: isSubmitting
                    ? null
                    : () => _reviewWithComment(context, 'defer'),
                child: const Text('Отложить'),
              ),
              TextButton(
                onPressed: isSubmitting
                    ? null
                    : () => _reviewWithComment(context, 'research'),
                child: const Text('Нужно исследование'),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Future<void> _changePrice(BuildContext context) async {
    final controller = TextEditingController(
      text: recommendation.recommendedPrice?.toStringAsFixed(2),
    );
    final approved = await showDialog<double>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Изменить решение'),
        content: TextField(
          controller: controller,
          autofocus: true,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: InputDecoration(
            labelText: 'Цена, ${recommendation.currency}',
            helperText: 'Решение не публикуется автоматически',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () {
              final value = double.tryParse(
                controller.text.trim().replaceAll(',', '.'),
              );
              if (value != null && value > 0) {
                Navigator.of(dialogContext).pop(value);
              }
            },
            child: const Text('Сохранить'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (approved != null && context.mounted) {
      final floor = recommendation.approvedPriceFloor;
      final belowFloor = floor != null && approved < floor;
      if (belowFloor) {
        final confirmed = await _confirmBelowFloor(context, approved, floor);
        if (!confirmed || !context.mounted) return;
      }
      await onReview(
        operation: 'accept',
        reasonCode: 'other',
        approvedPrice: approved,
        comment: 'Цена изменена оператором',
        allowBelowFloor: belowFloor,
        belowFloorWarningConfirmed: belowFloor,
      );
    }
  }

  Future<bool> _confirmBelowFloor(
    BuildContext context,
    double approved,
    double floor,
  ) async {
    var acknowledged = false;
    return await showDialog<bool>(
          context: context,
          barrierDismissible: false,
          builder: (dialogContext) => StatefulBuilder(
            builder: (context, setState) => AlertDialog(
              title: const Text('Цена ниже одобренного floor'),
              content: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${approved.toStringAsFixed(2)} ниже ${floor.toStringAsFixed(2)} ${recommendation.currency}. Это может нарушить ограничение маржи.',
                  ),
                  const SizedBox(height: 10),
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    value: acknowledged,
                    title: const Text(
                      'Я понимаю предупреждение и явно разрешаю решение ниже floor',
                    ),
                    onChanged: (value) =>
                        setState(() => acknowledged = value ?? false),
                  ),
                ],
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.of(dialogContext).pop(false),
                  child: const Text('Отмена'),
                ),
                FilledButton(
                  onPressed: acknowledged
                      ? () => Navigator.of(dialogContext).pop(true)
                      : null,
                  child: const Text('Подтвердить риск'),
                ),
              ],
            ),
          ),
        ) ??
        false;
  }

  Future<void> _reviewWithComment(
    BuildContext context,
    String operation,
  ) async {
    final result = await showDialog<({String reason, String comment})>(
      context: context,
      builder: (dialogContext) => const _RecommendationReasonDialog(),
    );
    if (result != null && context.mounted) {
      await onReview(
        operation: operation,
        reasonCode: result.reason,
        comment: result.comment,
        allowBelowFloor: false,
        belowFloorWarningConfirmed: false,
      );
    }
  }

  static String _rangeText(FitmentMarketRecommendation recommendation) {
    final minimum = recommendation.rangeMin;
    final maximum = recommendation.rangeMax;
    if (minimum == null || maximum == null) {
      return 'Надёжный рыночный диапазон пока не построен.';
    }
    return 'Рыночный диапазон: ${minimum.toStringAsFixed(2)}–${maximum.toStringAsFixed(2)} ${recommendation.currency}';
  }
}

class _PriceColumn extends StatelessWidget {
  const _PriceColumn({required this.recommendation});

  final FitmentMarketRecommendation recommendation;

  @override
  Widget build(BuildContext context) {
    final suggested = recommendation.recommendedPrice;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Text(
          '${recommendation.currentPrice.toStringAsFixed(2)} ${recommendation.currency}',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        Text(
          suggested == null
              ? '—'
              : '${suggested.toStringAsFixed(2)} ${recommendation.currency}',
          style: Theme.of(
            context,
          ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800),
        ),
      ],
    );
  }
}

class _RecommendationReasonDialog extends StatefulWidget {
  const _RecommendationReasonDialog();

  @override
  State<_RecommendationReasonDialog> createState() =>
      _RecommendationReasonDialogState();
}

class _RecommendationReasonDialogState
    extends State<_RecommendationReasonDialog> {
  final _comment = TextEditingController();
  String _reason = 'price_not_representative';

  @override
  void dispose() {
    _comment.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Причина решения'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          DropdownButtonFormField<String>(
            initialValue: _reason,
            items: const [
              DropdownMenuItem(
                value: 'price_not_representative',
                child: Text('Цена не репрезентативна'),
              ),
              DropdownMenuItem(
                value: 'incorrect_cross',
                child: Text('Ошибочный кросс'),
              ),
              DropdownMenuItem(
                value: 'wrong_quantity',
                child: Text('Неверное количество'),
              ),
              DropdownMenuItem(
                value: 'source_error',
                child: Text('Ошибка источника'),
              ),
              DropdownMenuItem(value: 'other', child: Text('Другое')),
            ],
            onChanged: (value) => setState(() => _reason = value ?? _reason),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _comment,
            maxLines: 3,
            decoration: const InputDecoration(
              labelText: 'Комментарий / ссылка на evidence',
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Отмена'),
        ),
        FilledButton(
          onPressed: () => Navigator.of(
            context,
          ).pop((reason: _reason, comment: _comment.text.trim())),
          child: const Text('Сохранить'),
        ),
      ],
    );
  }
}
