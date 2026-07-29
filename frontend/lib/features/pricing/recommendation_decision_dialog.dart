import 'package:flutter/material.dart';

import '../../core/marko_ui.dart';
import '../../core/presentation_formatters.dart';
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
  bool _declareBelowCost = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _price = TextEditingController(
      text: widget.recommendation.recommendedPrice == null
          ? ''
          : formatDecimalAmount(
              widget.recommendation.recommendedPrice!,
              priceTick: widget.recommendation.priceTick,
              fractionDigits: widget.recommendation.priceTickScale,
            ),
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
    final encryptedCostConfigured = _encryptedCostConfigured;
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
                      : 'Целевая цена: ${_money(widget.recommendation, target)}',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              if (widget.decision == 'overridden') ...[
                const SizedBox(height: 14),
                TextField(
                  controller: _price,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: InputDecoration(
                    labelText: 'Ваша цена, ${widget.recommendation.currency}',
                  ),
                  onChanged: (_) => setState(() {
                    _error = null;
                    _declareBelowCost = false;
                  }),
                ),
              ],
              if (widget.decision != 'rejected') ...[
                const SizedBox(height: 14),
                if (_serverCostMode && !encryptedCostConfigured)
                  const MarkoInlineMessage(
                    message:
                        'Для этой позиции себестоимость ещё не сохранена. Сервер не сможет проверить решение на убыточность.',
                    tone: MarkoMessageTone.warning,
                  ),
                if (_recommendedPriceBelowCost)
                  const MarkoInlineMessage(
                    message:
                        'Рекомендованная цена ниже сохранённой себестоимости. Для записи решения нужно явное подтверждение.',
                    tone: MarkoMessageTone.warning,
                  ),
                if (!_serverCostMode || encryptedCostConfigured)
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    value: _declareBelowCost,
                    title: Text(
                      _serverCostMode
                          ? 'Разрешаю ручное решение ниже зашифрованной себестоимости'
                          : 'По моей локальной себестоимости эта цена убыточна',
                    ),
                    subtitle: Text(
                      _serverCostMode
                          ? 'Сервер проверит цену после отправки. Исходная себестоимость не возвращается в интерфейс или audit trail.'
                          : 'Сумма себестоимости не отправляется в API; в audit trail попадёт только эта отметка.',
                    ),
                    onChanged: (value) => setState(() {
                      _declareBelowCost = value ?? false;
                    }),
                  ),
                if (_declareBelowCost)
                  const MarkoInlineMessage(
                    message:
                        'Убыточная цена требует ручного решения и причины. Себестоимость не является жёстким floor.',
                    tone: MarkoMessageTone.warning,
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

  bool get _serverCostMode =>
      widget.recommendation.contextSnapshot['cost_privacy_mode']?.toString() ==
      'SERVER_SIDE_ENCRYPTED';

  bool get _encryptedCostConfigured =>
      _serverCostMode &&
      widget.recommendation.contextSnapshot['cost_configured'] == true;

  bool get _recommendedPriceBelowCost =>
      _encryptedCostConfigured &&
      widget.recommendation.contextSnapshot['recommended_price_below_cost'] ==
          true;

  void _submit() {
    final target = _targetPrice;
    if (widget.decision != 'rejected' && (target == null || target <= 0)) {
      setState(() => _error = 'Укажите положительную цену');
      return;
    }
    if (widget.decision == 'accepted' &&
        _recommendedPriceBelowCost &&
        !_declareBelowCost) {
      setState(
        () => _error =
            'Подтвердите ручное решение ниже зашифрованной себестоимости',
      );
      return;
    }
    if (_reason.text.trim().length < 3) {
      setState(() => _error = 'Укажите причину решения');
      return;
    }
    final payload = <String, dynamic>{
      'decision': widget.decision,
      'allow_below_cost': _declareBelowCost,
      'warning_confirmed': _declareBelowCost,
      'reason': _reason.text.trim(),
    };
    if (widget.decision == 'overridden' && target != null) {
      payload['new_price'] = formatDecimalAmount(
        target,
        priceTick: widget.recommendation.priceTick,
        fractionDigits: widget.recommendation.priceTickScale,
      );
    }
    Navigator.of(context).pop(payload);
  }
}

String _money(PricingRecommendation recommendation, double value) =>
    formatMoney(
      value,
      currency: recommendation.currency,
      priceTick: recommendation.priceTick,
      fractionDigits: recommendation.priceTickScale,
    );

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
