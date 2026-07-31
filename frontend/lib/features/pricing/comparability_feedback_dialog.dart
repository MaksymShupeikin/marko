import 'package:flutter/material.dart';

import '../../core/app_language.dart';
import '../../core/marko_ui.dart';
import 'pricing_models.dart';

Future<Map<String, dynamic>?> showComparabilityFeedbackDialog(
  BuildContext context, {
  required ComparabilityReview review,
}) {
  return showDialog<Map<String, dynamic>>(
    context: context,
    builder: (_) => _ComparabilityFeedbackDialog(review: review),
  );
}

class _ComparabilityFeedbackDialog extends StatefulWidget {
  const _ComparabilityFeedbackDialog({required this.review});

  final ComparabilityReview review;

  @override
  State<_ComparabilityFeedbackDialog> createState() =>
      _ComparabilityFeedbackDialogState();
}

class _ComparabilityFeedbackDialogState
    extends State<_ComparabilityFeedbackDialog> {
  String _decision = 'CONFIRM';
  late String _verdict;
  late String _matchLevel;
  late double _confidence;
  late final TextEditingController _reason;
  String? _error;

  @override
  void initState() {
    super.initState();
    _verdict = widget.review.verdict;
    _matchLevel = widget.review.matchLevel;
    _confidence = widget.review.confidence.clamp(0, 1);
    _reason = TextEditingController();
  }

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final correcting = _decision == 'CORRECT';
    final hasHardStop = widget.review.hardStopConflicts.isNotEmpty;
    return AlertDialog(
      scrollable: true,
      title: Text(
        context.localized(
          ru: 'Проверка сопоставимости',
          uk: 'Перевірка зіставності',
        ),
      ),
      content: SizedBox(
        width: 520,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              context.localized(
                ru:
                    'Ответ сохранится как размеченный эталон. Он влияет только '
                    'на следующие ценовые расчёты; Marko не меняет цену на Prom.ua.',
                uk:
                    'Відповідь збережеться як розмічений еталон. Вона впливає '
                    'лише на наступні цінові розрахунки; Marko не змінює ціну на Prom.ua.',
              ),
            ),
            const SizedBox(height: 16),
            SegmentedButton<String>(
              segments: [
                ButtonSegment(
                  value: 'CONFIRM',
                  label: Text(
                    context.localized(
                      ru: 'Подтвердить вывод',
                      uk: 'Підтвердити висновок',
                    ),
                  ),
                  icon: const Icon(Icons.check_circle_outline),
                ),
                ButtonSegment(
                  value: 'CORRECT',
                  label: Text(
                    context.localized(ru: 'Исправить', uk: 'Виправити'),
                  ),
                  icon: const Icon(Icons.edit_outlined),
                ),
              ],
              selected: {_decision},
              onSelectionChanged: (value) {
                setState(() {
                  _decision = value.single;
                  _error = null;
                });
              },
            ),
            if (correcting) ...[
              const SizedBox(height: 16),
              DropdownButtonFormField<String>(
                initialValue: _verdict,
                isExpanded: true,
                decoration: InputDecoration(
                  labelText: context.localized(ru: 'Вердикт', uk: 'Вердикт'),
                ),
                items: _verdicts
                    .where((value) => value != 'COMPARABLE' || !hasHardStop)
                    .map(
                      (value) => DropdownMenuItem(
                        value: value,
                        child: Text(_verdictLabel(context, value)),
                      ),
                    )
                    .toList(growable: false),
                onChanged: (value) {
                  if (value == null) return;
                  setState(() {
                    _verdict = value;
                    _matchLevel = value == 'COMPARABLE'
                        ? 'ACCEPTABLE_ANALOGUE'
                        : 'SUSPICIOUS';
                  });
                },
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                key: ValueKey('$_verdict/$_matchLevel'),
                initialValue: _matchLevel,
                isExpanded: true,
                decoration: InputDecoration(
                  labelText: context.localized(
                    ru: 'Уровень совпадения',
                    uk: 'Рівень збігу',
                  ),
                ),
                items:
                    (_verdict == 'COMPARABLE'
                            ? _positiveLevels
                            : _negativeLevels)
                        .map(
                          (value) => DropdownMenuItem(
                            value: value,
                            child: Text(_levelLabel(context, value)),
                          ),
                        )
                        .toList(growable: false),
                onChanged: (value) =>
                    setState(() => _matchLevel = value ?? _matchLevel),
              ),
              const SizedBox(height: 12),
              Text(
                context.localized(
                  ru: 'Уверенность: ${(_confidence * 100).round()}%',
                  uk: 'Впевненість: ${(_confidence * 100).round()}%',
                ),
              ),
              Slider(
                value: _confidence,
                divisions: 20,
                label: '${(_confidence * 100).round()}%',
                onChanged: (value) => setState(() => _confidence = value),
              ),
            ],
            if (hasHardStop) ...[
              const SizedBox(height: 10),
              MarkoInlineMessage(
                message: context.localized(
                  ru:
                      'Есть жёсткое противоречие. Его нельзя исправить '
                      'положительным человеческим вердиктом.',
                  uk:
                      'Є жорстка суперечність. Її не можна виправити '
                      'позитивним людським вердиктом.',
                ),
                tone: MarkoMessageTone.warning,
              ),
            ],
            const SizedBox(height: 14),
            TextField(
              controller: _reason,
              minLines: 2,
              maxLines: 5,
              decoration: InputDecoration(
                labelText: context.localized(
                  ru: 'Почему вы подтверждаете или исправляете вывод',
                  uk: 'Чому ви підтверджуєте або виправляєте висновок',
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
    final reason = _reason.text.trim();
    if (reason.length < 3) {
      setState(() {
        _error = context.localized(
          ru: 'Укажите основание решения',
          uk: 'Укажіть підставу рішення',
        );
      });
      return;
    }
    Navigator.of(context).pop({
      'decision': _decision,
      'corrected_verdict': _decision == 'CORRECT' ? _verdict : null,
      'corrected_match_level': _decision == 'CORRECT' ? _matchLevel : null,
      'confidence': _decision == 'CORRECT' ? _confidence : null,
      'reason': reason,
      'evidence_corrections': <Map<String, dynamic>>[],
    });
  }
}

const _verdicts = <String>['COMPARABLE', 'NOT_COMPARABLE', 'INSUFFICIENT_DATA'];
const _positiveLevels = <String>['EXACT', 'ACCEPTABLE_ANALOGUE'];
const _negativeLevels = <String>['SUSPICIOUS', 'NOT_APPLICABLE'];

String _verdictLabel(BuildContext context, String value) => switch (value) {
  'COMPARABLE' => context.localized(ru: 'Сопоставим', uk: 'Зіставний'),
  'NOT_COMPARABLE' => context.localized(
    ru: 'Не сопоставим',
    uk: 'Не зіставний',
  ),
  _ => context.localized(ru: 'Недостаточно данных', uk: 'Недостатньо даних'),
};

String _levelLabel(BuildContext context, String value) => switch (value) {
  'EXACT' => context.localized(ru: 'Полное совпадение', uk: 'Повний збіг'),
  'ACCEPTABLE_ANALOGUE' => context.localized(
    ru: 'Допустимый аналог',
    uk: 'Допустимий аналог',
  ),
  'NOT_APPLICABLE' => context.localized(
    ru: 'Не применимо',
    uk: 'Не застосовується',
  ),
  _ => context.localized(ru: 'Сомнительный', uk: 'Сумнівний'),
};
