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
  late String _identityVerdict;
  late String _identityMatchLevel;
  late String _pricingAdmission;
  late double _confidence;
  late final TextEditingController _reason;
  String? _error;

  @override
  void initState() {
    super.initState();
    _identityVerdict = widget.review.identityVerdict;
    _identityMatchLevel = widget.review.identityMatchLevel;
    _pricingAdmission = widget.review.pricingAdmission;
    if (widget.review.hardStopConflicts.isNotEmpty &&
        _pricingAdmission == 'ADMITTED') {
      _pricingAdmission = 'EXCLUDED';
    }
    _confidence = widget.review.decisionConfidence.clamp(0, 1);
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
                initialValue: _identityVerdict,
                isExpanded: true,
                decoration: InputDecoration(
                  labelText: context.localized(
                    ru: 'Identity verdict',
                    uk: 'Identity verdict',
                  ),
                ),
                items: _identityVerdicts
                    .map(
                      (value) => DropdownMenuItem(
                        value: value,
                        child: Text(_identityVerdictLabel(context, value)),
                      ),
                    )
                    .toList(growable: false),
                onChanged: (value) {
                  if (value == null) return;
                  setState(() {
                    _identityVerdict = value;
                    _identityMatchLevel = value == 'MATCH'
                        ? 'ACCEPTABLE_ANALOGUE'
                        : 'SUSPICIOUS';
                    if (value != 'MATCH' && _pricingAdmission == 'ADMITTED') {
                      _pricingAdmission = value == 'NOT_MATCH'
                          ? 'EXCLUDED'
                          : 'MANUAL_REVIEW';
                    }
                  });
                },
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                key: ValueKey('$_identityVerdict/$_identityMatchLevel'),
                initialValue: _identityMatchLevel,
                isExpanded: true,
                decoration: InputDecoration(
                  labelText: context.localized(
                    ru: 'Уровень совпадения',
                    uk: 'Рівень збігу',
                  ),
                ),
                items:
                    (_identityVerdict == 'MATCH'
                            ? _positiveLevels
                            : _negativeLevels)
                        .map(
                          (value) => DropdownMenuItem(
                            value: value,
                            child: Text(_levelLabel(context, value)),
                          ),
                        )
                        .toList(growable: false),
                onChanged: (value) => setState(
                  () => _identityMatchLevel = value ?? _identityMatchLevel,
                ),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                key: ValueKey(
                  '$_identityVerdict/$_pricingAdmission/$hasHardStop',
                ),
                initialValue: _pricingAdmission,
                isExpanded: true,
                decoration: InputDecoration(
                  labelText: context.localized(
                    ru: 'Pricing admission',
                    uk: 'Pricing admission',
                  ),
                ),
                items: _pricingAdmissions
                    .where(
                      (value) =>
                          value != 'ADMITTED' ||
                          (_identityVerdict == 'MATCH' && !hasHardStop),
                    )
                    .map(
                      (value) => DropdownMenuItem(
                        value: value,
                        child: Text(_pricingAdmissionLabel(context, value)),
                      ),
                    )
                    .toList(growable: false),
                onChanged: (value) => setState(
                  () => _pricingAdmission = value ?? _pricingAdmission,
                ),
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
      'corrected_identity_verdict': _decision == 'CORRECT'
          ? _identityVerdict
          : null,
      'corrected_identity_match_level': _decision == 'CORRECT'
          ? _identityMatchLevel
          : null,
      'corrected_pricing_admission': _decision == 'CORRECT'
          ? _pricingAdmission
          : null,
      'confidence': _decision == 'CORRECT' ? _confidence : null,
      'reason': reason,
      'evidence_corrections': <Map<String, dynamic>>[],
    });
  }
}

const _identityVerdicts = <String>['MATCH', 'NOT_MATCH', 'MANUAL_REVIEW'];
const _positiveLevels = <String>['EXACT', 'ACCEPTABLE_ANALOGUE'];
const _negativeLevels = <String>['SUSPICIOUS', 'NOT_APPLICABLE'];
const _pricingAdmissions = <String>['ADMITTED', 'EXCLUDED', 'MANUAL_REVIEW'];

String _identityVerdictLabel(BuildContext context, String value) =>
    switch (value) {
      'MATCH' => context.localized(ru: 'Совпадает', uk: 'Збігається'),
      'NOT_MATCH' => context.localized(ru: 'Не совпадает', uk: 'Не збігається'),
      _ => context.localized(ru: 'Ручная проверка', uk: 'Ручна перевірка'),
    };

String _pricingAdmissionLabel(BuildContext context, String value) =>
    switch (value) {
      'ADMITTED' => context.localized(
        ru: 'Допущен в цену',
        uk: 'Допущено до ціни',
      ),
      'EXCLUDED' => context.localized(ru: 'Исключён', uk: 'Виключено'),
      _ => context.localized(ru: 'Ручная проверка', uk: 'Ручна перевірка'),
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
