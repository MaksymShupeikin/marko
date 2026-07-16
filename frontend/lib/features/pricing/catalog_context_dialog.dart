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
  late bool _allowBelowCost;
  String? _error;
  late final TextEditingController _cost;
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
  late final TextEditingController _floor;
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
    _allowBelowCost =
        _status == 'dead_stock' && snapshot['allow_below_cost'] == true;
    _cost = TextEditingController(text: _initialValue('cost'));
    _quantity = TextEditingController(text: _initialValue('stock_qty'));
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
      text: _initialValue('urgency', fallback: '1'),
    );
    _floor = TextEditingController(text: _initialValue('below_cost_floor'));
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
    _floor.dispose();
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
                  if (_status != 'dead_stock') _allowBelowCost = false;
                }),
              ),
              const SizedBox(height: 12),
              _NumberField(controller: _cost, label: 'Себестоимость, ₴'),
              const SizedBox(height: 12),
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
              const SizedBox(height: 10),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: _allowBelowCost,
                title: const Text('Разрешить цену ниже себестоимости'),
                subtitle: const Text(
                  'Только для неликвида; решение попадёт в audit trail.',
                ),
                onChanged: _status == 'dead_stock'
                    ? (value) => setState(() {
                        _allowBelowCost = value ?? false;
                      })
                    : null,
              ),
              if (_allowBelowCost) ...[
                const MarkoInlineMessage(
                  message:
                      'Укажите абсолютный нижний предел. Система не опустится ниже него.',
                  tone: MarkoMessageTone.warning,
                ),
                const SizedBox(height: 10),
                _NumberField(controller: _floor, label: 'Минимальная цена, ₴'),
              ],
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
    late final String? floor;
    try {
      cost = _optionalNumber(_cost.text, 'себестоимость');
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
      floor = _optionalNumber(_floor.text, 'минимальную цену', allowZero: true);
    } on FormatException catch (error) {
      setState(() => _error = error.message);
      return;
    }
    if (_allowBelowCost && floor == null) {
      setState(() => _error = 'Укажите минимальную цену');
      return;
    }
    if (_reason.text.trim().length < 3) {
      setState(() => _error = 'Укажите причину изменения');
      return;
    }
    final payload = <String, dynamic>{
      'stock_status': _status,
      'allow_below_cost': _allowBelowCost,
      'below_cost_warning_confirmed': _allowBelowCost,
      'reason': _reason.text.trim(),
    };
    if (cost != null) payload['cost'] = cost;
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
    if (_allowBelowCost && floor != null) payload['below_cost_floor'] = floor;
    Navigator.of(context).pop(payload);
  }

  String _initialValue(String key, {String fallback = ''}) {
    return widget.initialContext[key]?.toString() ?? fallback;
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
  const _NumberField({required this.controller, required this.label});

  final TextEditingController controller;
  final String label;

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      keyboardType: const TextInputType.numberWithOptions(decimal: true),
      decoration: InputDecoration(labelText: label),
    );
  }
}
