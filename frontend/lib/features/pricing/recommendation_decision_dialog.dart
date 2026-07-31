import 'package:flutter/material.dart';

import '../../core/app_language.dart';
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
  bool _reasonInitialized = false;
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
    _reason = TextEditingController();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_reasonInitialized) return;
    _reason.text = _defaultReason(context, widget.decision);
    _reasonInitialized = true;
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
      title: Text(_title(context, widget.decision)),
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
                      ? context.localized(
                          ru: 'Цена не указана',
                          uk: 'Ціну не вказано',
                        )
                      : context.localized(
                          ru: 'Целевая цена: ${_money(widget.recommendation, target)}',
                          uk: 'Цільова ціна: ${_money(widget.recommendation, target)}',
                        ),
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
                    labelText: context.localized(
                      ru: 'Ваша цена, ${widget.recommendation.currency}',
                      uk: 'Ваша ціна, ${widget.recommendation.currency}',
                    ),
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
                  MarkoInlineMessage(
                    message: context.localized(
                      ru: 'Для этой позиции себестоимость ещё не сохранена. Сервер не сможет проверить решение на убыточность.',
                      uk: 'Для цієї позиції собівартість ще не збережено. Сервер не зможе перевірити рішення на збитковість.',
                    ),
                    tone: MarkoMessageTone.warning,
                  ),
                if (_recommendedPriceBelowCost)
                  MarkoInlineMessage(
                    message: context.localized(
                      ru: 'Рекомендованная цена ниже сохранённой себестоимости. Для записи решения нужно явное подтверждение.',
                      uk: 'Рекомендована ціна нижча за збережену собівартість. Для запису рішення потрібне явне підтвердження.',
                    ),
                    tone: MarkoMessageTone.warning,
                  ),
                if (!_serverCostMode || encryptedCostConfigured)
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    value: _declareBelowCost,
                    title: Text(
                      _serverCostMode
                          ? context.localized(
                              ru: 'Разрешаю ручное решение ниже зашифрованной себестоимости',
                              uk: 'Дозволяю ручне рішення нижче зашифрованої собівартості',
                            )
                          : context.localized(
                              ru: 'По моей локальной себестоимости эта цена убыточна',
                              uk: 'За моєю локальною собівартістю ця ціна збиткова',
                            ),
                    ),
                    subtitle: Text(
                      _serverCostMode
                          ? context.localized(
                              ru: 'Сервер проверит цену после отправки. Исходная себестоимость не возвращается в интерфейс или журнал аудита.',
                              uk: 'Сервер перевірить ціну після надсилання. Початкова собівартість не повертається в інтерфейс або журнал аудиту.',
                            )
                          : context.localized(
                              ru: 'Сумма себестоимости не отправляется в API; в журнал аудита попадёт только эта отметка.',
                              uk: 'Сума собівартості не надсилається в API; до журналу аудиту потрапить лише ця позначка.',
                            ),
                    ),
                    onChanged: (value) => setState(() {
                      _declareBelowCost = value ?? false;
                    }),
                  ),
                if (_declareBelowCost)
                  MarkoInlineMessage(
                    message: context.localized(
                      ru: 'Убыточная цена требует ручного решения и причины. Себестоимость не является жёстким ценовым полом.',
                      uk: 'Збиткова ціна потребує ручного рішення та причини. Собівартість не є жорсткою ціновою підлогою.',
                    ),
                    tone: MarkoMessageTone.warning,
                  ),
              ],
              const SizedBox(height: 14),
              TextField(
                controller: _reason,
                minLines: 2,
                maxLines: 4,
                decoration: InputDecoration(
                  labelText: context.localized(ru: 'Причина', uk: 'Причина'),
                ),
              ),
              const SizedBox(height: 10),
              Text(
                context.localized(
                  ru: 'Решение запишется в Marko; цена на Prom.ua не меняется автоматически.',
                  uk: 'Рішення буде записано в Marko; ціна на Prom.ua не змінюється автоматично.',
                ),
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
          child: Text(context.localized(ru: 'Отмена', uk: 'Скасувати')),
        ),
        FilledButton(
          onPressed: _submit,
          child: Text(context.localized(ru: 'Записать', uk: 'Записати')),
        ),
      ],
    );
  }

  DecimalValue? get _targetPrice {
    if (widget.decision == 'rejected') return null;
    if (widget.decision == 'accepted') {
      return widget.recommendation.recommendedPrice;
    }
    return DecimalValue.tryParse(_price.text.trim().replaceAll(',', '.'));
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
      setState(
        () => _error = context.localized(
          ru: 'Укажите положительную цену',
          uk: 'Укажіть додатну ціну',
        ),
      );
      return;
    }
    if (widget.decision == 'accepted' &&
        _recommendedPriceBelowCost &&
        !_declareBelowCost) {
      setState(
        () => _error = context.localized(
          ru: 'Подтвердите ручное решение ниже зашифрованной себестоимости',
          uk: 'Підтвердьте ручне рішення нижче зашифрованої собівартості',
        ),
      );
      return;
    }
    if (_reason.text.trim().length < 3) {
      setState(
        () => _error = context.localized(
          ru: 'Укажите причину решения',
          uk: 'Укажіть причину рішення',
        ),
      );
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

String _money(PricingRecommendation recommendation, DecimalValue value) =>
    formatMoney(
      value,
      currency: recommendation.currency,
      priceTick: recommendation.priceTick,
      fractionDigits: recommendation.priceTickScale,
    );

String _title(BuildContext context, String decision) => switch (decision) {
  'accepted' => context.localized(
    ru: 'Принять рекомендацию',
    uk: 'Прийняти рекомендацію',
  ),
  'overridden' => context.localized(
    ru: 'Указать свою цену',
    uk: 'Вказати власну ціну',
  ),
  _ => context.localized(
    ru: 'Отклонить рекомендацию',
    uk: 'Відхилити рекомендацію',
  ),
};

String _defaultReason(BuildContext context, String decision) =>
    switch (decision) {
      'accepted' => context.localized(
        ru: 'Рекомендация принята оператором',
        uk: 'Рекомендацію прийнято оператором',
      ),
      'overridden' => context.localized(
        ru: 'Цена изменена оператором',
        uk: 'Ціну змінено оператором',
      ),
      _ => context.localized(
        ru: 'Рекомендация отклонена оператором',
        uk: 'Рекомендацію відхилено оператором',
      ),
    };
