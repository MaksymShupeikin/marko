part of '../recommendations_page.dart';

class _SummaryRow extends StatelessWidget {
  const _SummaryRow({
    required this.total,
    required this.raiseCount,
    required this.lowerCount,
    required this.reviewCount,
  });

  final int total;
  final int raiseCount;
  final int lowerCount;
  final int reviewCount;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth >= 760 ? 4 : 2;
        final width = (constraints.maxWidth - (columns - 1) * 12) / columns;
        return Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            _SummaryMetric(
              width: width,
              value: '$total',
              label: context.localized(
                ru: 'Позиций в расчёте',
                uk: 'Позицій у розрахунку',
              ),
            ),
            _SummaryMetric(
              width: width,
              value: '$raiseCount',
              label: context.localized(ru: 'Поднять', uk: 'Підвищити'),
              tone: _Tone.positive,
            ),
            _SummaryMetric(
              width: width,
              value: '$lowerCount',
              label: context.localized(ru: 'Снизить', uk: 'Знизити'),
              tone: _Tone.warning,
            ),
            _SummaryMetric(
              width: width,
              value: '$reviewCount',
              label: context.localized(ru: 'Проверить', uk: 'Перевірити'),
              tone: _Tone.negative,
            ),
          ],
        );
      },
    );
  }
}

enum _Tone { neutral, positive, warning, negative }

class _SummaryMetric extends StatelessWidget {
  const _SummaryMetric({
    required this.width,
    required this.value,
    required this.label,
    this.tone = _Tone.neutral,
  });

  final double width;
  final String value;
  final String label;
  final _Tone tone;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final foreground = switch (tone) {
      _Tone.positive => colors.positive,
      _Tone.warning => colors.warning,
      _Tone.negative => colors.negative,
      _ => colors.ink,
    };
    return SizedBox(
      width: width,
      child: MarkoPanel(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              value,
              style: Theme.of(
                context,
              ).textTheme.headlineSmall?.copyWith(color: foreground),
            ),
            const SizedBox(height: 4),
            Text(label, style: Theme.of(context).textTheme.bodySmall),
          ],
        ),
      ),
    );
  }
}
