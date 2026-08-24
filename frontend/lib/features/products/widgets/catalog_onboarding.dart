import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:heroicons/heroicons.dart';

import '../../../core/app_theme.dart';
import '../../../core/marko_ui.dart';
import '../../../core/widgets/marko_button.dart';
import 'catalog_filters.dart';
import 'source_panel.dart';

/// What a brand new account sees instead of the catalog: how the first import
/// works on the left, the same two source cards as the import modal on the
/// right. The toolbar, search and filters only appear once products exist.
class CatalogOnboarding extends StatelessWidget {
  const CatalogOnboarding({super.key});

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        const cards = CatalogSourceCards();
        // На вузькому екрані спершу дають імпортувати, і лише тим, у кого не
        // вийшло, показують кроки — за роздільником, як «або через пошту».
        if (constraints.maxWidth < 900) {
          return const Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _Instructions(steps: false),
              SizedBox(height: MarkoSpace.xl),
              cards,
              SizedBox(height: MarkoSpace.xxl),
              MarkoLabelledDivider(label: 'Інструкція, якщо щось не виходить'),
              SizedBox(height: MarkoSpace.xl),
              _Instructions(intro: false),
            ],
          );
        }
        return const Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _Instructions(steps: false),
            SizedBox(height: MarkoSpace.xl),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(flex: 5, child: cards),
                SizedBox(width: MarkoSpace.xxxl),
                Expanded(flex: 6, child: _Instructions(intro: false)),
              ],
            ),
          ],
        );
      },
    );
  }
}

class _Step {
  const _Step({required this.title, required this.body, required this.icon});

  final String title;
  final String body;
  final HeroIcons icon;
}

const _steps = [
  _Step(
    title: 'Експортуйте каталог із Prom.ua',
    body:
        'У кабінеті Prom.ua відкрийте «Товари та послуги», натисніть «Експорт» і виберіть формат XLSX.',
    icon: HeroIcons.arrowDownTray,
  ),
  _Step(
    title: 'Завантажте XLSX-файл у Marko',
    body:
        'Оберіть експортований XLSX-файл на пристрої. Marko імпортує назви, ціни, бренди, OEM-номери та артикули виробників.',
    icon: HeroIcons.bolt,
  ),
  _Step(
    title: 'Перевіряйте ціни конкурентів',
    body:
        'Відкрийте товар або знайдіть його за OEM, щоб побачити мінімальну й медіанну ціни та пропозиції на Avto.pro.',
    icon: HeroIcons.presentationChartLine,
  ),
];

class _Instructions extends StatelessWidget {
  const _Instructions({this.intro = true, this.steps = true});

  /// Заголовок із підзаголовком і самі кроки на мобілці роз'їжджаються
  /// в різні кінці екрана, тому кожну половину можна показати окремо.
  final bool intro;
  final bool steps;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (intro) ...[
          Text(
            'Додайте товари з XLSX-вивантаження',
            style: Theme.of(
              context,
            ).textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: MarkoSpace.sm),
          Text(
            'Експортуйте асортимент із кабінету Prom.ua та завантажте '
            'файл у Marko. Після обробки стануть доступні каталог, пошук, фільтри й аналітика цін конкурентів.',
            style: Theme.of(
              context,
            ).textTheme.bodyMedium?.copyWith(color: colors.muted, height: 1.45),
          ),
        ],
        if (intro && steps) const SizedBox(height: MarkoSpace.xl),
        if (steps)
          for (var i = 0; i < _steps.length; i++) ...[
            if (i > 0) const SizedBox(height: MarkoSpace.md),
            _StepRow(index: i + 1, step: _steps[i]),
          ],
      ],
    );
  }
}

class _StepRow extends StatelessWidget {
  const _StepRow({required this.index, required this.step});

  final int index;
  final _Step step;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      padding: const EdgeInsets.all(MarkoSpace.md),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(MarkoRadius.md),
        border: Border.all(color: colors.border),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 32,
            height: 32,
            decoration: BoxDecoration(
              color: colors.brandSoft,
              borderRadius: BorderRadius.circular(MarkoRadius.md),
              border: Border.all(color: colors.brand.withValues(alpha: 0.2)),
            ),
            alignment: Alignment.center,
            child: Text(
              '0$index',
              style: MarkoType.price.copyWith(
                color: colors.brand,
                fontSize: 13,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          const SizedBox(width: MarkoSpace.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  step.title,
                  style: Theme.of(
                    context,
                  ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 3),
                Text(
                  step.body,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: colors.muted,
                    height: 1.4,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class EmptyCatalog extends ConsumerWidget {
  const EmptyCatalog({
    required this.query,
    this.hasActiveFilters = false,
    super.key,
  });

  final String query;
  final bool hasActiveFilters;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final searching = query.trim().isNotEmpty;
    final filtered = hasActiveFilters || searching;

    return MarkoEmptyState(
      icon: filtered ? HeroIcons.magnifyingGlass : HeroIcons.archiveBox,
      title: filtered ? 'Нічого не знайдено' : 'Товарів поки немає',
      description: filtered
          ? 'Спробуйте змінити пошуковий запит або скиньте активні фільтри.'
          : 'Додайте каталог із Prom або завантажте XLSX.',
      action: filtered
          ? MarkoButton(
              label: 'Скинути фільтри',
              icon: HeroIcons.arrowPath,
              variant: MarkoButtonVariant.secondary,
              onPressed: () => resetCatalogFilters(ref),
            )
          : MarkoButton(
              label: 'Імпорт каталогу',
              icon: HeroIcons.arrowDownTray,
              onPressed: () => showCatalogImport(context),
            ),
    );
  }
}
