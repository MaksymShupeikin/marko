import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../core/app_language.dart';
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
  late final TextEditingController _reason;
  bool _reasonInitialized = false;

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
    _reason = TextEditingController();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_reasonInitialized) return;
    _reason.text = context.localized(
      ru: 'Ручное обновление контекста',
      uk: 'Ручне оновлення контексту',
    );
    _reasonInitialized = true;
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
    final fieldWidth = math.min(
      250.0,
      math.max(1.0, MediaQuery.sizeOf(context).width - 128),
    );
    return AlertDialog(
      scrollable: true,
      title: Text(
        context.localized(ru: 'Контекст склада', uk: 'Контекст складу'),
      ),
      content: SizedBox(
        width: 560,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              context.localized(
                ru: 'Это версионируемый ручной контекст: XLSX не меняется, а новые значения применятся в следующем прогоне.',
                uk: 'Це версійний ручний контекст: XLSX не змінюється, а нові значення застосуються в наступному розрахунку.',
              ),
            ),
            const SizedBox(height: 18),
            DropdownButtonFormField<String>(
              initialValue: _status,
              isExpanded: true,
              decoration: InputDecoration(
                labelText: context.localized(
                  ru: 'Статус товара',
                  uk: 'Статус товару',
                ),
              ),
              items: [
                DropdownMenuItem(
                  value: 'fresh',
                  child: Text(context.localized(ru: 'Ходовой', uk: 'Ходовий')),
                ),
                DropdownMenuItem(
                  value: 'stale',
                  child: Text(
                    context.localized(ru: 'Залежалый', uk: 'Залежаний'),
                  ),
                ),
                DropdownMenuItem(
                  value: 'dead_stock',
                  child: Text(
                    context.localized(ru: 'Неликвид', uk: 'Неліквід'),
                  ),
                ),
                DropdownMenuItem(
                  value: 'unknown',
                  child: Text(
                    context.localized(ru: 'Не указан', uk: 'Не вказано'),
                  ),
                ),
              ],
              onChanged: (value) => setState(() {
                _status = value ?? 'unknown';
              }),
            ),
            const SizedBox(height: 12),
            if (_serverCostEnabled) ...[
              MarkoInlineMessage(
                message: _costConfigured
                    ? context.localized(
                        ru: 'Себестоимость сохранена в зашифрованном виде. Текущее значение намеренно не возвращается из API; введите новое только для замены.',
                        uk: 'Собівартість збережено в зашифрованому вигляді. Поточне значення навмисно не повертається з API; введіть нове лише для заміни.',
                      )
                    : context.localized(
                        ru: 'Себестоимость будет зашифрована сервером AES-256-GCM. В ответах API, расчётных снимках и повторе исходное значение не показывается.',
                        uk: 'Собівартість буде зашифровано сервером AES-256-GCM. У відповідях API, розрахункових знімках і повторі початкове значення не показується.',
                      ),
                tone: MarkoMessageTone.success,
              ),
              const SizedBox(height: 12),
              _NumberField(
                controller: _cost,
                label: _costConfigured
                    ? context.localized(
                        ru: 'Новая себестоимость, UAH (не менять — пусто)',
                        uk: 'Нова собівартість, UAH (не змінювати — порожньо)',
                      )
                    : context.localized(
                        ru: 'Себестоимость, UAH',
                        uk: 'Собівартість, UAH',
                      ),
                enabled: !_clearCost,
              ),
              if (_costConfigured)
                CheckboxListTile(
                  contentPadding: EdgeInsets.zero,
                  value: _clearCost,
                  title: Text(
                    context.localized(
                      ru: 'Удалить сохранённую себестоимость',
                      uk: 'Видалити збережену собівартість',
                    ),
                  ),
                  subtitle: Text(
                    context.localized(
                      ru: 'Будет создана аудируемая запись удаления без раскрытия старого значения.',
                      uk: 'Буде створено аудований запис видалення без розкриття старого значення.',
                    ),
                  ),
                  onChanged: (value) => setState(() {
                    _clearCost = value ?? false;
                    if (_clearCost) _cost.clear();
                  }),
                ),
            ] else
              MarkoInlineMessage(
                message: context.localized(
                  ru: 'Ввод себестоимости отключён: серверное хранилище ключей не активировано.',
                  uk: 'Введення собівартості вимкнено: серверне сховище ключів не активовано.',
                ),
                tone: MarkoMessageTone.warning,
              ),
            const SizedBox(height: 14),
            Wrap(
              spacing: 12,
              runSpacing: 12,
              children: [
                for (final field in [
                  _NumberField(
                    controller: _quantity,
                    label: context.localized(
                      ru: 'Остаток, шт.',
                      uk: 'Залишок, шт.',
                    ),
                  ),
                  _NumberField(
                    controller: _age,
                    label: context.localized(
                      ru: 'Возраст запаса, дней',
                      uk: 'Вік запасу, днів',
                    ),
                  ),
                  _NumberField(
                    controller: _monthlySales,
                    label: context.localized(
                      ru: 'Ожидаемых продаж/мес.',
                      uk: 'Очікуваних продажів/міс.',
                    ),
                  ),
                  _NumberField(
                    controller: _sales30,
                    label: context.localized(
                      ru: 'Продано за 30 дней',
                      uk: 'Продано за 30 днів',
                    ),
                  ),
                  _NumberField(
                    controller: _sales60,
                    label: context.localized(
                      ru: 'Продано за 60 дней',
                      uk: 'Продано за 60 днів',
                    ),
                  ),
                  _NumberField(
                    controller: _sales90,
                    label: context.localized(
                      ru: 'Продано за 90 дней',
                      uk: 'Продано за 90 днів',
                    ),
                  ),
                  _NumberField(
                    controller: _daysSinceSale,
                    label: context.localized(
                      ru: 'Дней с последней продажи',
                      uk: 'Днів з останнього продажу',
                    ),
                  ),
                  _NumberField(
                    controller: _historicalMonthly,
                    label: context.localized(
                      ru: 'Исторических продаж/мес.',
                      uk: 'Історичних продажів/міс.',
                    ),
                  ),
                  _NumberField(
                    controller: _views30,
                    label: context.localized(
                      ru: 'Просмотров за 30 дней',
                      uk: 'Переглядів за 30 днів',
                    ),
                  ),
                  _NumberField(
                    controller: _conversion,
                    label: 'Conversion proxy (0–1)',
                  ),
                  _NumberField(
                    controller: _priority,
                    label: context.localized(
                      ru: 'Ручной вес приоритета',
                      uk: 'Ручна вага пріоритету',
                    ),
                  ),
                  _NumberField(
                    controller: _liquidity,
                    label: context.localized(
                      ru: 'Цель ликвидности (0–1)',
                      uk: 'Ціль ліквідності (0–1)',
                    ),
                  ),
                  _NumberField(
                    controller: _urgency,
                    label: context.localized(
                      ru: 'Срочность (0–1)',
                      uk: 'Терміновість (0–1)',
                    ),
                  ),
                ])
                  SizedBox(width: fieldWidth, child: field),
              ],
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _reason,
              minLines: 1,
              maxLines: 3,
              decoration: InputDecoration(
                labelText: context.localized(
                  ru: 'Причина изменения',
                  uk: 'Причина зміни',
                ),
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
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: Text(context.localized(ru: 'Отмена', uk: 'Скасувати')),
        ),
        FilledButton(
          onPressed: _submit,
          child: Text(context.localized(ru: 'Сохранить', uk: 'Зберегти')),
        ),
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
      quantity = _optionalNumber(
        _quantity.text,
        context.localized(ru: 'остаток', uk: 'залишок'),
        allowZero: true,
      );
      age = _optionalNumber(
        _age.text,
        context.localized(ru: 'возраст', uk: 'вік'),
        allowZero: true,
      );
      monthlySales = _optionalNumber(
        _monthlySales.text,
        context.localized(ru: 'продажи', uk: 'продажі'),
        allowZero: true,
      );
      sales30 = _optionalNumber(
        _sales30.text,
        context.localized(ru: 'продажи за 30 дней', uk: 'продажі за 30 днів'),
        allowZero: true,
      );
      sales60 = _optionalNumber(
        _sales60.text,
        context.localized(ru: 'продажи за 60 дней', uk: 'продажі за 60 днів'),
        allowZero: true,
      );
      sales90 = _optionalNumber(
        _sales90.text,
        context.localized(ru: 'продажи за 90 дней', uk: 'продажі за 90 днів'),
        allowZero: true,
      );
      daysSinceSale = _optionalNumber(
        _daysSinceSale.text,
        context.localized(
          ru: 'дни с последней продажи',
          uk: 'дні з останнього продажу',
        ),
        allowZero: true,
      );
      historicalMonthly = _optionalNumber(
        _historicalMonthly.text,
        context.localized(ru: 'исторические продажи', uk: 'історичні продажі'),
        allowZero: true,
      );
      views30 = _optionalNumber(
        _views30.text,
        context.localized(ru: 'просмотры', uk: 'перегляди'),
        allowZero: true,
      );
      conversion = _optionalNumber(
        _conversion.text,
        'conversion proxy',
        allowZero: true,
        max: 1,
      );
      priority = _optionalNumber(
        _priority.text,
        context.localized(ru: 'вес приоритета', uk: 'вага пріоритету'),
      );
      liquidity = _optionalNumber(
        _liquidity.text,
        context.localized(ru: 'цель ликвидности', uk: 'ціль ліквідності'),
        allowZero: true,
        max: 1,
      );
      urgency = _optionalNumber(
        _urgency.text,
        context.localized(ru: 'срочность', uk: 'терміновість'),
        allowZero: true,
        max: 1,
      );
    } on FormatException catch (error) {
      setState(() => _error = error.message);
      return;
    }
    if (_reason.text.trim().length < 3) {
      setState(
        () => _error = context.localized(
          ru: 'Укажите причину изменения',
          uk: 'Укажіть причину зміни',
        ),
      );
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
      throw FormatException(
        context.localized(
          ru: 'Проверьте себестоимость: положительное число, максимум 2 знака после запятой',
          uk: 'Перевірте собівартість: додатне число, максимум 2 знаки після коми',
        ),
      );
    }
    final parsed = double.tryParse(normalized);
    if (parsed == null || !parsed.isFinite || parsed <= 0) {
      throw FormatException(
        context.localized(
          ru: 'Проверьте себестоимость: значение должно быть больше нуля',
          uk: 'Перевірте собівартість: значення має бути більшим за нуль',
        ),
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
      throw FormatException(
        context.localized(
          ru: 'Проверьте $label: нужно число',
          uk: 'Перевірте $label: потрібне число',
        ),
      );
    }
    if (parsed < 0 || (!allowZero && parsed == 0)) {
      throw FormatException(
        context.localized(
          ru: 'Проверьте $label: значение должно быть ${allowZero ? 'неотрицательным' : 'больше нуля'}',
          uk: 'Перевірте $label: значення має бути ${allowZero ? 'невід’ємним' : 'більшим за нуль'}',
        ),
      );
    }
    if (max != null && parsed > max) {
      throw FormatException(
        context.localized(
          ru: 'Проверьте $label: максимум $max',
          uk: 'Перевірте $label: максимум $max',
        ),
      );
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
