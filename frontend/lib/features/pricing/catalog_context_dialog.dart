import 'package:flutter/material.dart';

import '../../core/marko_ui.dart';

Future<Map<String, dynamic>?> showCatalogContextDialog(
  BuildContext context, {
  required String initialStatus,
  required Map<String, dynamic> initialContext,
}) {
  return showDialog<Map<String, dynamic>>(
    context: context,
    builder: (_) => _CatalogContextDialog(
      initialStatus: initialStatus,
      initialContext: initialContext,
    ),
  );
}

class _CatalogContextDialog extends StatefulWidget {
  const _CatalogContextDialog({
    required this.initialStatus,
    required this.initialContext,
  });

  final String initialStatus;
  final Map<String, dynamic> initialContext;

  @override
  State<_CatalogContextDialog> createState() => _CatalogContextDialogState();
}

class _CatalogContextDialogState extends State<_CatalogContextDialog> {
  late String _status;
  String? _error;
  late final TextEditingController _cost;
  bool _clearCost = false;
  late final TextEditingController _quantity;
  late final TextEditingController _age;
  late final TextEditingController _monthlySales;
  late final TextEditingController _sales30;
  late final TextEditingController _sales60;
  late final TextEditingController _sales90;
  late final TextEditingController _daysSinceSale;
  late final TextEditingController _historicalMonthly;
  late final TextEditingController _views30;
  late final TextEditingController _conversion;
  late final TextEditingController _priority;
  late final TextEditingController _liquidity;
  late final TextEditingController _urgency;
  final _reason = TextEditingController(text: 'Ручное обновление контекста');

  @override
  void initState() {
    super.initState();
    final snapshot = widget.initialContext;
    final snapshotStatus = snapshot['stock_status']?.toString();
    _status =
        const {
          'fresh',
          'stale',
          'dead_stock',
          'unknown',
        }.contains(snapshotStatus)
        ? snapshotStatus!
        : const {
            'fresh',
            'stale',
            'dead_stock',
            'unknown',
          }.contains(widget.initialStatus)
        ? widget.initialStatus
        : 'unknown';
    _quantity = TextEditingController(text: _initialValue('stock_qty'));
    _cost = TextEditingController();
    _age = TextEditingController(text: _initialValue('stock_age_days'));
    _monthlySales = TextEditingController(
      text: _initialValue('expected_units_sold'),
    );
    _sales30 = TextEditingController(text: _initialValue('units_sold_30d'));
    _sales60 = TextEditingController(text: _initialValue('units_sold_60d'));
    _sales90 = TextEditingController(text: _initialValue('units_sold_90d'));
    _daysSinceSale = TextEditingController(
      text: _initialValue('days_since_last_sale'),
    );
    _historicalMonthly = TextEditingController(
      text: _initialValue('historical_monthly_units'),
    );
    _views30 = TextEditingController(text: _initialValue('views_30d'));
    _conversion = TextEditingController(
      text: _initialValue('conversion_rate_proxy'),
    );
    _priority = TextEditingController(
      text: _initialValue('manual_priority', fallback: '1'),
    );
    _liquidity = TextEditingController(
      text: _initialValue('liquidity_target', fallback: '0'),
    );
    _urgency = TextEditingController(
      text: _initialValue('urgency', fallback: '0'),
    );
  }

  @override
  void dispose() {
    _cost.dispose();
    _quantity.dispose();
    _age.dispose();
    _monthlySales.dispose();
    _sales30.dispose();
    _sales60.dispose();
    _sales90.dispose();
    _daysSinceSale.dispose();
    _historicalMonthly.dispose();
    _views30.dispose();
    _conversion.dispose();
    _priority.dispose();
    _liquidity.dispose();
    _urgency.dispose();
    _reason.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Контекст склада'),
      content: SizedBox(
        width: 560,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text(
                'Это версионируемый ручной контекст: XLSX не меняется, а новые значения применятся в следующем прогоне.',
              ),
              const SizedBox(height: 18),
              DropdownButtonFormField<String>(
                initialValue: _status,
                decoration: const InputDecoration(labelText: 'Статус товара'),
                items: const [
                  DropdownMenuItem(value: 'fresh', child: Text('Ходовой')),
                  DropdownMenuItem(value: 'stale', child: Text('Залежалый')),
                  DropdownMenuItem(
                    value: 'dead_stock',
                    child: Text('Неликвид'),
                  ),
                  DropdownMenuItem(value: 'unknown', child: Text('Не указан')),
                ],
                onChanged: (value) => setState(() {
                  _status = value ?? 'unknown';
                }),
              ),
              const SizedBox(height: 12),
              if (_serverCostEnabled) ...[
                MarkoInlineMessage(
                  message: _costConfigured
                      ? 'Себестоимость сохранена в зашифрованном виде. Текущее значение намеренно не возвращается из API; введите новое только для замены.'
                      : 'Себестоимость будет зашифрована сервером AES-256-GCM. В API-ответах, расчётных snapshots и replay исходное значение не показывается.',
                  tone: MarkoMessageTone.success,
                ),
                const SizedBox(height: 12),
                _NumberField(
                  controller: _cost,
                  label: _costConfigured
                      ? 'Новая себестоимость, UAH (не менять — пусто)'
                      : 'Себестоимость, UAH',
                  enabled: !_clearCost,
                ),
                if (_costConfigured)
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    value: _clearCost,
                    title: const Text('Удалить сохранённую себестоимость'),
                    subtitle: const Text(
                      'Будет создана аудируемая запись удаления без раскрытия старого значения.',
                    ),
                    onChanged: (value) => setState(() {
                      _clearCost = value ?? false;
                      if (_clearCost) _cost.clear();
                    }),
                  ),
              ] else
                const MarkoInlineMessage(
                  message:
                      'Ввод себестоимости отключён: серверный encryption keyring не активирован.',
                  tone: MarkoMessageTone.warning,
                ),
              const SizedBox(height: 14),
              Wrap(
                spacing: 12,
                runSpacing: 12,
                children: [
                  SizedBox(
                    width: 250,
                    child: _NumberField(
                      controller: _quantity,
                      label: 'Остаток, шт.',
                    ),
                  ),
                  SizedBox(
                    width: 250,
                    child: _NumberField(
                      controller: _age,
                      label: 'Возраст запаса, дней',
                    ),
                  ),
                  SizedBox(
                    width: 250,
                    child: _NumberField(
                      controller: _monthlySales,
                      label: 'Ожидаемых продаж/мес.',
                    ),
                  ),
                  SizedBox(
                    width: 250,
                    child: _NumberField(
                      controller: _sales30,
                      label: 'Продано за 30 дней',
                    ),
                  ),
                  SizedBox(
                    width: 250,
                    child: _NumberField(
                      controller: _sales60,
                      label: 'Продано за 60 дней',
                    ),
                  ),
                  SizedBox(
                    width: 250,
                    child: _NumberField(
                      controller: _sales90,
                      label: 'Продано за 90 дней',
                    ),
                  ),
                  SizedBox(
                    width: 250,
                    child: _NumberField(
                      controller: _daysSinceSale,
                      label: 'Дней с последней продажи',
                    ),
                  ),
                  SizedBox(
                    width: 250,
                    child: _NumberField(
                      controller: _historicalMonthly,
                      label: 'Исторических продаж/мес.',
                    ),
                  ),
                  SizedBox(
                    width: 250,
                    child: _NumberField(
                      controller: _views30,
                      label: 'Просмотров за 30 дней',
                    ),
                  ),
                  SizedBox(
                    width: 250,
                    child: _NumberField(
                      controller: _conversion,
                      label: 'Conversion proxy (0–1)',
                    ),
                  ),
                  SizedBox(
                    width: 250,
                    child: _NumberField(
                      controller: _priority,
                      label: 'Ручной вес приоритета',
                    ),
                  ),
                  SizedBox(
                    width: 250,
                    child: _NumberField(
                      controller: _liquidity,
                      label: 'Цель ликвидности (0–1)',
                    ),
                  ),
                  SizedBox(
                    width: 250,
                    child: _NumberField(
                      controller: _urgency,
                      label: 'Срочность (0–1)',
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _reason,
                minLines: 1,
                maxLines: 3,
                decoration: const InputDecoration(
                  labelText: 'Причина изменения',
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
          child: const Text('Отмена'),
        ),
        FilledButton(onPressed: _submit, child: const Text('Сохранить')),
      ],
    );
  }

  void _submit() {
    late final String? cost;
    late final String? quantity;
    late final String? age;
    late final String? monthlySales;
    late final String? sales30;
    late final String? sales60;
    late final String? sales90;
    late final String? daysSinceSale;
    late final String? historicalMonthly;
    late final String? views30;
    late final String? conversion;
    late final String? priority;
    late final String? liquidity;
    late final String? urgency;
    try {
      cost = _serverCostEnabled && !_clearCost
          ? _optionalMoney(_cost.text)
          : null;
      quantity = _optionalNumber(_quantity.text, 'остаток', allowZero: true);
      age = _optionalNumber(_age.text, 'возраст', allowZero: true);
      monthlySales = _optionalNumber(
        _monthlySales.text,
        'продажи',
        allowZero: true,
      );
      sales30 = _optionalNumber(
        _sales30.text,
        'продажи за 30 дней',
        allowZero: true,
      );
      sales60 = _optionalNumber(
        _sales60.text,
        'продажи за 60 дней',
        allowZero: true,
      );
      sales90 = _optionalNumber(
        _sales90.text,
        'продажи за 90 дней',
        allowZero: true,
      );
      daysSinceSale = _optionalNumber(
        _daysSinceSale.text,
        'дни с последней продажи',
        allowZero: true,
      );
      historicalMonthly = _optionalNumber(
        _historicalMonthly.text,
        'исторические продажи',
        allowZero: true,
      );
      views30 = _optionalNumber(_views30.text, 'просмотры', allowZero: true);
      conversion = _optionalNumber(
        _conversion.text,
        'conversion proxy',
        allowZero: true,
        max: 1,
      );
      priority = _optionalNumber(_priority.text, 'вес приоритета');
      liquidity = _optionalNumber(
        _liquidity.text,
        'цель ликвидности',
        allowZero: true,
        max: 1,
      );
      urgency = _optionalNumber(
        _urgency.text,
        'срочность',
        allowZero: true,
        max: 1,
      );
    } on FormatException catch (error) {
      setState(() => _error = error.message);
      return;
    }
    if (_reason.text.trim().length < 3) {
      setState(() => _error = 'Укажите причину изменения');
      return;
    }
    final payload = <String, dynamic>{
      'stock_status': _status,
      'allow_below_cost': false,
      'below_cost_warning_confirmed': false,
      'reason': _reason.text.trim(),
    };
    if (cost != null) payload['cost'] = cost;
    if (_clearCost) payload['clear_cost'] = true;
    if (quantity != null) payload['stock_qty'] = quantity;
    if (age != null) payload['stock_age_days'] = age;
    if (monthlySales != null) payload['expected_units_sold'] = monthlySales;
    if (sales30 != null) payload['units_sold_30d'] = sales30;
    if (sales60 != null) payload['units_sold_60d'] = sales60;
    if (sales90 != null) payload['units_sold_90d'] = sales90;
    if (daysSinceSale != null) {
      payload['days_since_last_sale'] = daysSinceSale;
    }
    if (historicalMonthly != null) {
      payload['historical_monthly_units'] = historicalMonthly;
    }
    if (views30 != null) payload['views_30d'] = views30;
    if (conversion != null) payload['conversion_rate_proxy'] = conversion;
    if (priority != null) payload['manual_priority'] = priority;
    if (liquidity != null) payload['liquidity_target'] = liquidity;
    if (urgency != null) payload['urgency'] = urgency;
    Navigator.of(context).pop(payload);
  }

  String _initialValue(String key, {String fallback = ''}) {
    return widget.initialContext[key]?.toString() ?? fallback;
  }

  bool get _serverCostEnabled =>
      widget.initialContext['cost_privacy_mode']?.toString() ==
      'SERVER_SIDE_ENCRYPTED';

  bool get _costConfigured => widget.initialContext['cost_configured'] == true;

  String? _optionalMoney(String raw) {
    final normalized = raw.trim().replaceAll(',', '.');
    if (normalized.isEmpty) return null;
    if (!RegExp(r'^\d+(?:\.\d{1,2})?$').hasMatch(normalized)) {
      throw const FormatException(
        'Проверьте себестоимость: положительное число, максимум 2 знака после запятой',
      );
    }
    final parsed = double.tryParse(normalized);
    if (parsed == null || !parsed.isFinite || parsed <= 0) {
      throw const FormatException(
        'Проверьте себестоимость: значение должно быть больше нуля',
      );
    }
    return normalized;
  }

  String? _optionalNumber(
    String raw,
    String label, {
    bool allowZero = false,
    double? max,
  }) {
    final normalized = raw.trim().replaceAll(',', '.');
    if (normalized.isEmpty) return null;
    final parsed = double.tryParse(normalized);
    if (parsed == null || !parsed.isFinite) {
      throw FormatException('Проверьте $label: нужно число');
    }
    if (parsed < 0 || (!allowZero && parsed == 0)) {
      throw FormatException(
        'Проверьте $label: значение должно быть ${allowZero ? 'неотрицательным' : 'больше нуля'}',
      );
    }
    if (max != null && parsed > max) {
      throw FormatException('Проверьте $label: максимум $max');
    }
    return normalized;
  }
}

class _NumberField extends StatelessWidget {
  const _NumberField({
    required this.controller,
    required this.label,
    this.enabled = true,
  });

  final TextEditingController controller;
  final String label;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      enabled: enabled,
      keyboardType: const TextInputType.numberWithOptions(decimal: true),
      decoration: InputDecoration(labelText: label),
    );
  }
}
