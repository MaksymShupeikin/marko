import 'package:flutter/material.dart';

import '../../core/marko_ui.dart';
import 'pricing_models.dart';

Future<Map<String, dynamic>?> showRecommendationDecisionDialog(
  BuildContext context, {
  required PricingRecommendation recommendation,
  required String decision,
}) {
  return showDialog<Map<String, dynamic>>(
    context: context,
    builder: (_) => _RecommendationDecisionDialog(
      recommendation: recommendation,
      decision: decision,
    ),
  );
}

class _RecommendationDecisionDialog extends StatefulWidget {
  const _RecommendationDecisionDialog({
    required this.recommendation,
    required this.decision,
  });

  final PricingRecommendation recommendation;
  final String decision;

  @override
  State<_RecommendationDecisionDialog> createState() =>
      _RecommendationDecisionDialogState();
}

class _RecommendationDecisionDialogState
    extends State<_RecommendationDecisionDialog> {
  late final TextEditingController _price;
  late final TextEditingController _reason;
  bool _allowBelowCost = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _price = TextEditingController(
      text: widget.recommendation.recommendedPrice?.toStringAsFixed(2) ?? '',
    );
    _reason = TextEditingController(text: _defaultReason(widget.decision));
  }

  @override
  void dispose() {
    _price.dispose();
    _reason.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final target = _targetPrice;
    final cost = _number(widget.recommendation.contextSnapshot['cost']);
    final belowCost = target != null && cost != null && target < cost;
    return AlertDialog(
      title: Text(_title(widget.decision)),
      content: SizedBox(
        width: 480,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(widget.recommendation.name),
              const SizedBox(height: 12),
              if (widget.decision != 'rejected')
                Text(
                  target == null
                      ? 'Цена не указана'
                      : 'Целевая цена: ${_money(target)}',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              if (widget.decision == 'overridden') ...[
                const SizedBox(height: 14),
                TextField(
                  controller: _price,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: const InputDecoration(labelText: 'Ваша цена, ₴'),
                  onChanged: (_) => setState(() {
                    _error = null;
                    _allowBelowCost = false;
                  }),
                ),
              ],
              if (belowCost) ...[
                const SizedBox(height: 14),
                MarkoInlineMessage(
                  message:
                      'Цена ${_money(target)} ниже себестоимости ${_money(cost)}. Это разрешено только для неликвида и будет записано в журнал.',
                  tone: MarkoMessageTone.warning,
                ),
                CheckboxListTile(
                  contentPadding: EdgeInsets.zero,
                  value: _allowBelowCost,
                  title: const Text('Явно подтверждаю цену ниже себестоимости'),
                  onChanged: widget.recommendation.stockStatus == 'dead_stock'
                      ? (value) => setState(() {
                          _allowBelowCost = value ?? false;
                        })
                      : null,
                ),
              ],
              const SizedBox(height: 14),
              TextField(
                controller: _reason,
                minLines: 2,
                maxLines: 4,
                decoration: const InputDecoration(labelText: 'Причина'),
              ),
              const SizedBox(height: 10),
              const Text(
                'Решение запишется в Marko; цена на Prom.ua не меняется автоматически.',
              ),
              if (_error != null) ...[
                const SizedBox(height: 10),
                MarkoInlineMessage(
                  message: _error!,
                  tone: MarkoMessageTone.error,
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Отмена'),
        ),
        FilledButton(onPressed: _submit, child: const Text('Записать')),
      ],
    );
  }

  double? get _targetPrice {
    if (widget.decision == 'rejected') return null;
    if (widget.decision == 'accepted') {
      return widget.recommendation.recommendedPrice;
    }
    return double.tryParse(_price.text.trim().replaceAll(',', '.'));
  }

  void _submit() {
    final target = _targetPrice;
    if (widget.decision != 'rejected' && (target == null || target <= 0)) {
      setState(() => _error = 'Укажите положительную цену');
      return;
    }
    if (_reason.text.trim().length < 3) {
      setState(() => _error = 'Укажите причину решения');
      return;
    }
    final cost = _number(widget.recommendation.contextSnapshot['cost']);
    final belowCost = target != null && cost != null && target < cost;
    if (belowCost && widget.recommendation.stockStatus != 'dead_stock') {
      setState(
        () => _error = 'Цена ниже себестоимости доступна только для неликвида',
      );
      return;
    }
    if (belowCost && !_allowBelowCost) {
      setState(() => _error = 'Подтвердите цену ниже себестоимости');
      return;
    }
    final floor = _number(
      widget.recommendation.contextSnapshot['below_cost_floor'],
    );
    if (belowCost && floor != null && target < floor) {
      setState(() => _error = 'Цена ниже утверждённого floor ${_money(floor)}');
      return;
    }
    final payload = <String, dynamic>{
      'decision': widget.decision,
      'allow_below_cost': belowCost && _allowBelowCost,
      'warning_confirmed': belowCost && _allowBelowCost,
      'reason': _reason.text.trim(),
    };
    if (widget.decision == 'overridden' && target != null) {
      payload['new_price'] = target.toStringAsFixed(2);
    }
    Navigator.of(context).pop(payload);
  }
}

double? _number(dynamic value) =>
    value == null ? null : double.tryParse(value.toString());

String _money(double value) => '${value.toStringAsFixed(0)} ₴';

String _title(String decision) => switch (decision) {
  'accepted' => 'Принять рекомендацию',
  'overridden' => 'Указать свою цену',
  _ => 'Отклонить рекомендацию',
};

String _defaultReason(String decision) => switch (decision) {
  'accepted' => 'Рекомендация принята оператором',
  'overridden' => 'Цена изменена оператором',
  _ => 'Рекомендация отклонена оператором',
};
