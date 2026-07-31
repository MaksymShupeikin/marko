import 'package:flutter/material.dart';

import '../../core/app_language.dart';
import '../../core/app_theme.dart';
import '../../core/widgets/marko_cached_image.dart';
import 'pricing_models.dart';

class ComparabilityReviewPanel extends StatelessWidget {
  const ComparabilityReviewPanel({
    required this.evidence,
    this.onFeedback,
    this.onReview,
    super.key,
  });

  final RecommendationEvidence evidence;
  final Future<void> Function(RecommendationEvidence)? onFeedback;
  final Future<void> Function(RecommendationEvidence)? onReview;

  @override
  Widget build(BuildContext context) {
    final review = evidence.llmReview;
    if (review == null) {
      return _MissingReview(evidence: evidence, onReview: onReview);
    }

    final colors = MarkoTheme.of(context);
    final eligible = evidence.llmPricingEligible;
    final foreground = eligible
        ? colors.positive
        : review.verdict == 'NOT_COMPARABLE'
        ? colors.negative
        : colors.warning;
    final background = eligible
        ? colors.positiveSoft
        : review.verdict == 'NOT_COMPARABLE'
        ? colors.negativeSoft
        : colors.warningSoft;
    return Container(
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: foreground.withValues(alpha: 0.28)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 8,
            runSpacing: 6,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Icon(
                eligible
                    ? Icons.psychology_alt_rounded
                    : Icons.manage_search_rounded,
                size: 19,
                color: foreground,
              ),
              Text(
                '${_verdictLabel(context, review.verdict)} · '
                '${_levelLabel(context, review.matchLevel)} · '
                '${(review.confidence * 100).round()}%',
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: foreground,
                  fontWeight: FontWeight.w700,
                ),
              ),
              _SourceChip(review: review),
            ],
          ),
          const SizedBox(height: 7),
          Text(review.rationale),
          if (review.dimensionFindings.isNotEmpty) ...[
            const SizedBox(height: 8),
            ...review.dimensionFindings.map(
              (finding) => _FindingLine(finding: finding),
            ),
          ],
          if (review.hardStopConflicts.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              context.localized(
                ru: 'Жёсткие стоп-признаки',
                uk: 'Жорсткі стоп-ознаки',
              ),
              style: Theme.of(
                context,
              ).textTheme.labelLarge?.copyWith(color: colors.negative),
            ),
            ...review.hardStopConflicts.map(
              (conflict) =>
                  _HardStopLine(conflict: conflict, color: colors.negative),
            ),
          ],
          if (review.imageUrls.isNotEmpty) ...[
            const SizedBox(height: 9),
            Text(
              context.localized(
                ru: 'Фото, переданные в проверку',
                uk: 'Фото, передані на перевірку',
              ),
              style: Theme.of(context).textTheme.labelMedium,
            ),
            const SizedBox(height: 5),
            SizedBox(
              height: 70,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: review.imageUrls.length.clamp(0, 4),
                separatorBuilder: (_, _) => const SizedBox(width: 6),
                itemBuilder: (context, index) => ClipRRect(
                  borderRadius: BorderRadius.circular(6),
                  child: SizedBox(
                    width: 82,
                    child: MarkoCachedImage(imageUrl: review.imageUrls[index]),
                  ),
                ),
              ),
            ),
          ],
          if (review.errorCode != null) ...[
            const SizedBox(height: 7),
            Text(
              '${review.errorCode}: ${review.errorDetail ?? ''}',
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: colors.negative),
            ),
          ],
          const SizedBox(height: 8),
          Text(
            context.localized(
              ru:
                  'Проверка ${review.promptVersion} · ${review.modelId} · '
                  '${review.feedbackCount} отметок заказчика. '
                  'Цена на Prom.ua не публикуется автоматически.',
              uk:
                  'Перевірка ${review.promptVersion} · ${review.modelId} · '
                  '${review.feedbackCount} позначок замовника. '
                  'Ціна на Prom.ua не публікується автоматично.',
            ),
            style: Theme.of(context).textTheme.bodySmall,
          ),
          if (onFeedback != null || onReview != null) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 6,
              children: [
                if (onFeedback != null)
                  OutlinedButton.icon(
                    onPressed: () => onFeedback!(evidence),
                    icon: const Icon(Icons.fact_check_outlined, size: 17),
                    label: Text(
                      context.localized(
                        ru: 'Подтвердить / исправить',
                        uk: 'Підтвердити / виправити',
                      ),
                    ),
                  ),
                if (onReview != null)
                  TextButton.icon(
                    onPressed: () => onReview!(evidence),
                    icon: const Icon(Icons.refresh_rounded, size: 17),
                    label: Text(
                      context.localized(
                        ru: 'Проверить заново',
                        uk: 'Перевірити знову',
                      ),
                    ),
                  ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class _MissingReview extends StatelessWidget {
  const _MissingReview({required this.evidence, required this.onReview});

  final RecommendationEvidence evidence;
  final Future<void> Function(RecommendationEvidence)? onReview;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: colors.warningSoft,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          Icon(Icons.hourglass_empty_rounded, color: colors.warning, size: 19),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              evidence.llmReviewRequired
                  ? context.localized(
                      ru: 'LLM-проверки нет. Кандидат исключён из ценового расчёта.',
                      uk: 'LLM-перевірки немає. Кандидата виключено з цінового розрахунку.',
                    )
                  : context.localized(
                      ru: 'LLM-проверка не запускалась; действует детерминированный контур.',
                      uk: 'LLM-перевірка не запускалась; діє детермінований контур.',
                    ),
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
          if (onReview != null)
            TextButton(
              onPressed: () => onReview!(evidence),
              child: Text(context.localized(ru: 'Проверить', uk: 'Перевірити')),
            ),
        ],
      ),
    );
  }
}

class _FindingLine extends StatelessWidget {
  const _FindingLine({required this.finding});

  final Map<String, dynamic> finding;

  @override
  Widget build(BuildContext context) {
    final outcome = finding['outcome']?.toString() ?? 'UNKNOWN';
    final ourValue = finding['our_value']?.toString().trim() ?? '';
    final candidateValue = finding['candidate_value']?.toString().trim() ?? '';
    final references = _mapList(finding['evidence']);
    final colors = MarkoTheme.of(context);
    final color = switch (outcome) {
      'MATCH' => colors.positive,
      'CONFLICT' => colors.negative,
      _ => colors.muted,
    };
    return Padding(
      padding: const EdgeInsets.only(bottom: 3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text.rich(
            TextSpan(
              children: [
                TextSpan(
                  text:
                      '${_dimensionLabel(context, finding['dimension'])}: '
                      '$outcome · ',
                  style: TextStyle(color: color, fontWeight: FontWeight.w700),
                ),
                TextSpan(text: finding['explanation']?.toString() ?? '—'),
              ],
            ),
            style: Theme.of(context).textTheme.bodySmall,
          ),
          if (ourValue.isNotEmpty || candidateValue.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(left: 12, top: 2),
              child: Text(
                context.localized(
                  ru:
                      'Наше: ${ourValue.isEmpty ? '—' : ourValue} · '
                      'Кандидат: ${candidateValue.isEmpty ? '—' : candidateValue}',
                  uk:
                      'Наше: ${ourValue.isEmpty ? '—' : ourValue} · '
                      'Кандидат: ${candidateValue.isEmpty ? '—' : candidateValue}',
                ),
                style: Theme.of(
                  context,
                ).textTheme.bodySmall?.copyWith(color: colors.muted),
              ),
            ),
          if (references.isNotEmpty)
            _EvidenceReferences(references: references),
        ],
      ),
    );
  }
}

class _HardStopLine extends StatelessWidget {
  const _HardStopLine({required this.conflict, required this.color});

  final Map<String, dynamic> conflict;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final ourValue = conflict['our_value']?.toString().trim() ?? '';
    final candidateValue = conflict['candidate_value']?.toString().trim() ?? '';
    final references = _mapList(conflict['evidence']);
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '• ${_dimensionLabel(context, conflict['dimension'])}: '
            '${conflict['explanation'] ?? 'CONFLICT'}',
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: color),
          ),
          if (ourValue.isNotEmpty || candidateValue.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(left: 12, top: 2),
              child: Text(
                context.localized(
                  ru:
                      'Наше: ${ourValue.isEmpty ? '—' : ourValue} · '
                      'Кандидат: ${candidateValue.isEmpty ? '—' : candidateValue}',
                  uk:
                      'Наше: ${ourValue.isEmpty ? '—' : ourValue} · '
                      'Кандидат: ${candidateValue.isEmpty ? '—' : candidateValue}',
                ),
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
          if (references.isNotEmpty)
            _EvidenceReferences(references: references),
        ],
      ),
    );
  }
}

class _EvidenceReferences extends StatelessWidget {
  const _EvidenceReferences({required this.references});

  final List<Map<String, dynamic>> references;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Padding(
      padding: const EdgeInsets.only(left: 12, top: 2),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: references
            .map((reference) {
              final source = _evidenceSourceLabel(context, reference['source']);
              final field = reference['field']?.toString().trim() ?? '';
              final excerpt = reference['excerpt']?.toString().trim() ?? '';
              final value = reference['value']?.toString().trim() ?? '';
              final proof = excerpt.isNotEmpty ? excerpt : value;
              return Text(
                '↳ $source${field.isEmpty ? '' : ' · $field'}'
                '${proof.isEmpty ? '' : ': “$proof”'}',
                style: Theme.of(
                  context,
                ).textTheme.bodySmall?.copyWith(color: colors.muted),
              );
            })
            .toList(growable: false),
      ),
    );
  }
}

class _SourceChip extends StatelessWidget {
  const _SourceChip({required this.review});

  final ComparabilityReview review;

  @override
  Widget build(BuildContext context) {
    final cached = review.cacheHitReviewId != null;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface.withValues(alpha: 0.78),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(
        cached ? '${review.decisionSource} · CACHE' : review.decisionSource,
        style: Theme.of(context).textTheme.labelSmall,
      ),
    );
  }
}

String _verdictLabel(BuildContext context, String value) => switch (value) {
  'COMPARABLE' => context.localized(ru: 'Сопоставим', uk: 'Зіставний'),
  'NOT_COMPARABLE' => context.localized(
    ru: 'Не сопоставим',
    uk: 'Не зіставний',
  ),
  _ => context.localized(ru: 'Недостаточно данных', uk: 'Недостатньо даних'),
};

String _levelLabel(BuildContext context, String value) => switch (value) {
  'EXACT' => context.localized(ru: 'полное совпадение', uk: 'повний збіг'),
  'ACCEPTABLE_ANALOGUE' => context.localized(
    ru: 'допустимый аналог',
    uk: 'допустимий аналог',
  ),
  'NOT_APPLICABLE' => context.localized(
    ru: 'не применимо',
    uk: 'не застосовується',
  ),
  _ => context.localized(ru: 'сомнительный', uk: 'сумнівний'),
};

String _dimensionLabel(BuildContext context, Object? value) {
  return switch (value?.toString()) {
    'oe_reference' => 'OE',
    'part_type' => context.localized(ru: 'Тип детали', uk: 'Тип деталі'),
    'fitment' => context.localized(ru: 'Применимость', uk: 'Застосовність'),
    'vehicle_generation' => context.localized(ru: 'Поколение', uk: 'Покоління'),
    'year_interval' => context.localized(ru: 'Годы', uk: 'Роки'),
    'engine' => context.localized(ru: 'Двигатель', uk: 'Двигун'),
    'body_variant' => context.localized(ru: 'Кузов', uk: 'Кузов'),
    'side' => context.localized(ru: 'Сторона', uk: 'Сторона'),
    'position' => context.localized(ru: 'Позиция', uk: 'Позиція'),
    'condition' => context.localized(ru: 'Состояние', uk: 'Стан'),
    'package_quantity' => context.localized(
      ru: 'Комплектация',
      uk: 'Комплектація',
    ),
    'brand_manufacturer' => context.localized(ru: 'Бренд', uk: 'Бренд'),
    'currency_presence' => context.localized(ru: 'Валюта', uk: 'Валюта'),
    final String value when value.isNotEmpty => value,
    _ => context.localized(ru: 'Признак', uk: 'Ознака'),
  };
}

String _evidenceSourceLabel(BuildContext context, Object? value) {
  return switch (value?.toString()) {
    'OUR_PRODUCT' => context.localized(ru: 'Наш товар', uk: 'Наш товар'),
    'CANDIDATE' => context.localized(
      ru: 'Карточка конкурента',
      uk: 'Картка конкурента',
    ),
    'IMAGE' => context.localized(ru: 'Фото', uk: 'Фото'),
    'DETERMINISTIC_GATE' => context.localized(
      ru: 'Жёсткое правило',
      uk: 'Жорстке правило',
    ),
    final String value when value.isNotEmpty => value,
    _ => context.localized(ru: 'Источник', uk: 'Джерело'),
  };
}

List<Map<String, dynamic>> _mapList(Object? value) {
  if (value is! List) return const [];
  return value
      .whereType<Map>()
      .map((item) => item.map((key, value) => MapEntry(key.toString(), value)))
      .toList(growable: false);
}
