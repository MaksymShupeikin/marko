import 'package:flutter/material.dart';

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
      title: const Text('Уточнить уровень товара'),
      content: SizedBox(
        width: 440,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'Override сохраняется новой append-only классификацией и не переписывает исходное наблюдение.',
            ),
            const SizedBox(height: 16),
            DropdownButtonFormField<String>(
              initialValue: _tier,
              decoration: const InputDecoration(labelText: 'Уровень'),
              items: _tiers
                  .map(
                    (value) => DropdownMenuItem(
                      value: value,
                      child: Text(_tierLabel(value)),
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
              decoration: const InputDecoration(
                labelText: 'Основание классификации',
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
          child: const Text('Отмена'),
        ),
        FilledButton(onPressed: _submit, child: const Text('Сохранить')),
      ],
    );
  }

  void _submit() {
    final reason = _reason.text.trim();
    if (reason.length < 3) {
      setState(() => _error = 'Укажите основание override');
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

String _tierLabel(String value) => switch (value) {
  'oem' => 'OEM',
  'oes' => 'OES',
  'aftermarket_a' => 'Aftermarket A',
  'aftermarket_b' => 'Aftermarket B',
  'budget' => 'Бюджетный aftermarket',
  'kemp' => 'KEMP',
  'used' => 'Б/у или восстановленный',
  _ => 'Не определён',
};
