part of '../recommendations_page.dart';

class _QueueFilters extends StatelessWidget {
  const _QueueFilters({required this.selected, required this.onSelected});

  final String selected;
  final ValueChanged<String> onSelected;

  @override
  Widget build(BuildContext context) {
    final options = <(String, String)>[
      ('all', context.localized(ru: 'Все', uk: 'Усі')),
      (
        'raise',
        context.localized(ru: 'Недополученная маржа', uk: 'Недоотримана маржа'),
      ),
      (
        'clearance',
        context.localized(
          ru: 'Высвобождение капитала',
          uk: 'Вивільнення капіталу',
        ),
      ),
      (
        'review',
        context.localized(ru: 'Проверить вручную', uk: 'Перевірити вручну'),
      ),
      ('hold', context.localized(ru: 'Без изменения', uk: 'Без змін')),
    ];
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: options
          .map(
            (option) => ChoiceChip(
              label: Text(option.$2),
              selected: selected == option.$1,
              onSelected: (_) => onSelected(option.$1),
            ),
          )
          .toList(growable: false),
    );
  }
}
