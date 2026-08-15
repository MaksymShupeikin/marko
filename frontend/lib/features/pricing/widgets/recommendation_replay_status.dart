part of '../recommendations_page.dart';

class _ReplayStatus extends StatelessWidget {
  const _ReplayStatus({required this.replay});

  final RecommendationReplay replay;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final exact = replay.exactMatch;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: exact ? colors.positiveSoft : colors.negativeSoft,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          Icon(
            exact ? Icons.verified_rounded : Icons.warning_amber_rounded,
            color: exact ? colors.positive : colors.negative,
            size: 19,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              exact
                  ? context.localized(
                      ru: 'Replay совпал: ${replay.contractVersion}',
                      uk: 'Replay збігається: ${replay.contractVersion}',
                    )
                  : context.localized(
                      ru: 'Обнаружен drift: ${replay.mismatches.keys.join(', ')}',
                      uk: 'Виявлено drift: ${replay.mismatches.keys.join(', ')}',
                    ),
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: exact ? colors.positive : colors.negative,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
