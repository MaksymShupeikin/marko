part of '../recommendations_page.dart';

class _SortSelector extends StatelessWidget {
  const _SortSelector({required this.selected, required this.onSelected});

  final String selected;
  final ValueChanged<String> onSelected;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final entries = <MarkoMenuEntry<String>>[
      MarkoMenuEntry(
        value: 'ABSOLUTE_RECOMMENDED_CHANGE',
        label: context.localized(
          ru: 'Макс. изменение цены',
          uk: 'Макс. зміна ціни',
        ),
        icon: Icons.swap_vert_rounded,
      ),
      MarkoMenuEntry(
        value: 'PERCENT_RECOMMENDED_CHANGE',
        label: context.localized(
          ru: 'Макс. изменение, %',
          uk: 'Макс. зміна, %',
        ),
        icon: Icons.percent_rounded,
      ),
      MarkoMenuEntry(
        value: 'EXPECTED_GROSS_UPLIFT',
        label: context.localized(
          ru: 'Потенциал валовой маржи',
          uk: 'Потенціал валової маржі',
        ),
        icon: Icons.trending_up_rounded,
      ),
      MarkoMenuEntry(
        value: 'CLEARANCE_CAPITAL_LOCK',
        label: context.localized(
          ru: 'Замороженный капитал',
          uk: 'Заморожений капітал',
        ),
        icon: Icons.inventory_2_outlined,
      ),
      MarkoMenuEntry(
        value: 'REVIEW_PRIORITY',
        label: context.localized(
          ru: 'Приоритет проверки',
          uk: 'Пріоритет перевірки',
        ),
        icon: Icons.flag_outlined,
      ),
    ];
    final current = entries.firstWhere(
      (entry) => entry.value == selected,
      orElse: () => entries.first,
    );

    return MarkoMenuButton<String>(
      key: const ValueKey('recommendations-sort'),
      tooltip: context.localized(ru: 'Сортировка', uk: 'Сортування'),
      header: context.localized(ru: 'Сортировка', uk: 'Сортування'),
      selected: selected,
      onSelected: onSelected,
      entries: entries,
      minWidth: 288,
      maxWidth: 340,
      child: Container(
        width: 310,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        decoration: BoxDecoration(
          color: colors.surface,
          borderRadius: BorderRadius.circular(9),
          border: Border.all(color: colors.border),
        ),
        child: Row(
          children: [
            Icon(Icons.sort_rounded, size: 18, color: colors.muted),
            const SizedBox(width: 9),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    context.localized(ru: 'Сортировка', uk: 'Сортування'),
                    style: Theme.of(
                      context,
                    ).textTheme.labelSmall?.copyWith(color: colors.muted),
                  ),
                  Text(
                    current.label,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: colors.ink,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 6),
            Icon(
              Icons.keyboard_arrow_down_rounded,
              size: 18,
              color: colors.muted,
            ),
          ],
        ),
      ),
    );
  }
}
