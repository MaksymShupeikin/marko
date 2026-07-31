import 'package:flutter/material.dart';

import '../../core/app_language.dart';

Future<({String tier, String reason})?> showTierOverrideDialog(
  BuildContext context, {
  required String currentTier,
}) {
  return showDialog<({String tier, String reason})>(
    context: context,
    builder: (_) => _TierOverrideDialog(currentTier: currentTier),
  );
}

class _TierOverrideDialog extends StatefulWidget {
  const _TierOverrideDialog({required this.currentTier});

  final String currentTier;

  @override
  State<_TierOverrideDialog> createState() => _TierOverrideDialogState();
}

class _TierOverrideDialogState extends State<_TierOverrideDialog> {
  late String _tier;
  final _reason = TextEditingController();
  String? _error;

  @override
  void initState() {
    super.initState();
    _tier = _tiers.contains(widget.currentTier)
        ? widget.currentTier
        : 'unknown';
  }

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      scrollable: true,
      title: Text(
        context.localized(
          ru: 'Уточнить уровень товара',
          uk: 'Уточнити рівень товару',
        ),
      ),
      content: SizedBox(
        width: 440,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              context.localized(
                ru: 'Изменение сохраняется новой аудируемой классификацией и не переписывает исходное наблюдение.',
                uk: 'Зміну збережено новою аудованою класифікацією; початкове спостереження не переписується.',
              ),
            ),
            const SizedBox(height: 16),
            DropdownButtonFormField<String>(
              initialValue: _tier,
              isExpanded: true,
              decoration: InputDecoration(
                labelText: context.localized(ru: 'Уровень', uk: 'Рівень'),
              ),
              items: _tiers
                  .map(
                    (value) => DropdownMenuItem(
                      value: value,
                      child: Text(_tierLabel(context, value)),
                    ),
                  )
                  .toList(growable: false),
              onChanged: (value) => setState(() => _tier = value ?? _tier),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _reason,
              minLines: 2,
              maxLines: 4,
              decoration: InputDecoration(
                labelText: context.localized(
                  ru: 'Основание классификации',
                  uk: 'Підстава класифікації',
                ),
              ),
            ),
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
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
    final reason = _reason.text.trim();
    if (reason.length < 3) {
      setState(
        () => _error = context.localized(
          ru: 'Укажите основание изменения',
          uk: 'Укажіть підставу зміни',
        ),
      );
      return;
    }
    Navigator.of(context).pop((tier: _tier, reason: reason));
  }
}

const _tiers = <String>[
  'oem',
  'oes',
  'aftermarket_a',
  'aftermarket_b',
  'budget',
  'kemp',
  'used',
  'unknown',
];

String _tierLabel(BuildContext context, String value) => switch (value) {
  'oem' => 'OEM',
  'oes' => 'OES',
  'aftermarket_a' => 'Aftermarket A',
  'aftermarket_b' => 'Aftermarket B',
  'budget' => context.localized(
    ru: 'Бюджетный aftermarket',
    uk: 'Бюджетний aftermarket',
  ),
  'kemp' => 'KEMP',
  'used' => context.localized(
    ru: 'Б/у или восстановленный',
    uk: 'Вживаний або відновлений',
  ),
  _ => context.localized(ru: 'Не определён', uk: 'Не визначено'),
};
