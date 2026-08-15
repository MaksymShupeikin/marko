part of '../recommendations_page.dart';

class _CatalogEvidenceBadge extends StatelessWidget {
  const _CatalogEvidenceBadge({required this.evidence});

  final CatalogDataEvidence evidence;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final (label, foreground, background, icon) = switch (evidence.status) {
      'OE_CONFIRMED' => (
        context.localized(ru: 'OE подтверждён', uk: 'OE підтверджено'),
        colors.positive,
        colors.positiveSoft,
        Icons.verified_outlined,
      ),
      'MPN_ONLY' => (
        context.localized(ru: 'MPN · только поиск', uk: 'MPN · лише пошук'),
        colors.warning,
        colors.warningSoft,
        Icons.manage_search_rounded,
      ),
      'CANDIDATE_REVIEW' => (
        context.localized(
          ru: 'Кандидат · ручная проверка',
          uk: 'Кандидат · ручна перевірка',
        ),
        colors.warning,
        colors.warningSoft,
        Icons.rule_folder_outlined,
      ),
      _ => (
        context.localized(
          ru: 'Нет OE · ручная проверка',
          uk: 'Немає OE · ручна перевірка',
        ),
        colors.negative,
        colors.negativeSoft,
        Icons.warning_amber_rounded,
      ),
    };

    return Tooltip(
      message: _catalogEvidenceTooltip(context, evidence, label),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          color: background,
          borderRadius: BorderRadius.circular(7),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 14, color: foreground),
            const SizedBox(width: 4),
            Flexible(
              child: Text(
                label,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: foreground,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

String _catalogEvidenceTooltip(
  BuildContext context,
  CatalogDataEvidence evidence,
  String label,
) {
  final lines = <String>[label];
  if (evidence.internalCode?.trim().isNotEmpty ?? false) {
    lines.add(
      '${context.localized(ru: 'Внутренний код', uk: 'Внутрішній код')}: '
      '${evidence.internalCode}',
    );
  }
  if (evidence.oeSources.isNotEmpty) {
    lines.add(
      '${context.localized(ru: 'Источники OE', uk: 'Джерела OE')}: '
      '${evidence.oeSources.take(3).join(', ')}',
    );
  }
  if (evidence.candidateNumbers.isNotEmpty) {
    lines.add(
      '${context.localized(ru: 'Кандидаты', uk: 'Кандидати')}: '
      '${evidence.candidateNumbers.take(3).join(', ')}',
    );
  }
  if (evidence.reviewOnly) {
    lines.add(
      context.localized(
        ru: 'Ценовой допуск не расширяется',
        uk: 'Ціновий допуск не розширюється',
      ),
    );
  }
  return lines.join('\n');
}

class _CatalogDataEvidencePanel extends StatelessWidget {
  const _CatalogDataEvidencePanel({required this.recommendation});

  final PricingRecommendation recommendation;

  @override
  Widget build(BuildContext context) {
    final evidence = recommendation.catalogDataEvidence;
    final muted = Theme.of(context).textTheme.bodySmall;
    final url = evidence.evidenceUrl;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: MarkoTheme.of(context).surfaceMuted.withValues(alpha: 0.72),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  Icons.inventory_2_outlined,
                  size: 18,
                  color: MarkoTheme.of(context).muted,
                ),
                const SizedBox(width: 7),
                Expanded(
                  child: Text(
                    context.localized(
                      ru: 'Данные текущего каталога',
                      uk: 'Дані поточного каталогу',
                    ),
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            _CatalogEvidenceBadge(evidence: evidence),
            if (evidence.internalCode?.trim().isNotEmpty ?? false)
              Text(
                '${context.localized(ru: 'Внутренний код', uk: 'Внутрішній код')}: '
                '${evidence.internalCode}',
                style: muted,
              ),
            if (evidence.oeSources.isNotEmpty)
              Text(
                '${context.localized(ru: 'Источники OE', uk: 'Джерела OE')}: '
                '${evidence.oeSources.join(', ')}',
                style: muted,
              ),
            if (evidence.confirmedCrossNumbers.isNotEmpty)
              Text(
                '${context.localized(ru: 'Другие подтверждённые номера', uk: 'Інші підтверджені номери')}: '
                '${evidence.confirmedCrossNumbers.join(', ')}',
                style: muted,
              ),
            if (evidence.candidateNumbers.isNotEmpty)
              Text(
                '${context.localized(ru: 'Кандидаты (не подтверждены)', uk: 'Кандидати (не підтверджені)')}: '
                '${evidence.candidateNumbers.join(', ')}',
                style: muted,
              ),
            if (evidence.anomalies.isNotEmpty)
              Text(
                '${context.localized(ru: 'Аномалии', uk: 'Аномалії')}: '
                '${evidence.anomalies.join(', ')}',
                style: muted,
              ),
            if (evidence.noOeReason?.trim().isNotEmpty ?? false)
              Text(
                '${context.localized(ru: 'Почему нет OE', uk: 'Чому немає OE')}: '
                '${evidence.noOeReason}',
                style: muted,
              ),
            if (evidence.reviewOnly)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(
                  context.localized(
                    ru: 'Кандидаты и MPN показаны для работы оператора и не становятся подтверждённым OE автоматически.',
                    uk: 'Кандидати та MPN показані для роботи оператора і не стають підтвердженим OE автоматично.',
                  ),
                  style: muted,
                ),
              ),
            if (url != null) ...[
              const SizedBox(height: 4),
              TextButton.icon(
                onPressed: () async {
                  final uri = Uri.tryParse(url);
                  if (uri == null ||
                      !{'http', 'https'}.contains(uri.scheme.toLowerCase())) {
                    return;
                  }
                  await launchUrl(uri, mode: LaunchMode.externalApplication);
                },
                icon: const Icon(Icons.open_in_new_rounded, size: 16),
                label: Text(
                  context.localized(
                    ru: 'Открыть подтверждение',
                    uk: 'Відкрити підтвердження',
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
