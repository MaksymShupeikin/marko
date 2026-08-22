import 'package:flutter/material.dart';
import 'package:heroicons/heroicons.dart';

import '../../../core/app_theme.dart';
import '../../../core/widgets/marko_button.dart';

/// Opens the concise, unified user manual and tips dialog.
Future<void> showHelpOverlay(BuildContext context) {
  if (MediaQuery.sizeOf(context).width < 700) {
    return showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => const _HelpSheet(),
    );
  }
  return showDialog<void>(
    context: context,
    barrierDismissible: true,
    builder: (context) => const _HelpDialog(),
  );
}

enum _HelpSection {
  quickstart('Швидкий старт', HeroIcons.bolt),
  importCatalog('Імпорт каталогу', HeroIcons.arrowDownTray),
  searchAndFilter('Пошук & OEM', HeroIcons.magnifyingGlass),
  competitors('Ціни Avto.pro', HeroIcons.presentationChartLine),
  pricing('Ціноутворення', HeroIcons.banknotes);

  const _HelpSection(this.label, this.icon);
  final String label;
  final HeroIcons icon;
}

class _HelpSheet extends StatelessWidget {
  const _HelpSheet();

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      constraints: BoxConstraints(
        maxHeight: MediaQuery.sizeOf(context).height * 0.90,
      ),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: const BorderRadius.vertical(
          top: Radius.circular(MarkoRadius.xl),
        ),
        boxShadow: MarkoShadow.overlay,
      ),
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      clipBehavior: Clip.antiAlias,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Center(
            child: Container(
              margin: const EdgeInsets.only(top: 10, bottom: 4),
              width: 36,
              height: 4,
              decoration: BoxDecoration(
                color: colors.borderStrong,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ),
          const Expanded(child: _HelpContent(isCompact: true)),
        ],
      ),
    );
  }
}

class _HelpDialog extends StatelessWidget {
  const _HelpDialog();

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Dialog(
      backgroundColor: Colors.transparent,
      insetPadding: const EdgeInsets.symmetric(
        horizontal: MarkoSpace.xxl,
        vertical: MarkoSpace.xxl,
      ),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 780, maxHeight: 720),
        child: Container(
          decoration: BoxDecoration(
            color: colors.surface,
            borderRadius: BorderRadius.circular(MarkoRadius.xl),
            border: Border.all(color: colors.border),
            boxShadow: MarkoShadow.overlay,
          ),
          clipBehavior: Clip.antiAlias,
          child: const _HelpContent(isCompact: false),
        ),
      ),
    );
  }
}

class _HelpContent extends StatefulWidget {
  const _HelpContent({required this.isCompact});

  final bool isCompact;

  @override
  State<_HelpContent> createState() => _HelpContentState();
}

class _HelpContentState extends State<_HelpContent> {
  _HelpSection _active = _HelpSection.quickstart;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final isCompact = widget.isCompact;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _buildHeader(context, colors),
        _buildTabs(colors),
        const Divider(height: 1),
        Expanded(
          child: SingleChildScrollView(
            padding: EdgeInsets.all(isCompact ? MarkoSpace.lg : MarkoSpace.xxl),
            child: _buildSection(context, colors),
          ),
        ),
        const Divider(height: 1),
        _buildFooter(context, colors, isCompact),
      ],
    );
  }

  Widget _buildHeader(BuildContext context, MarkoTheme colors) {
    return Container(
      padding: const EdgeInsets.fromLTRB(
        MarkoSpace.xl,
        MarkoSpace.lg,
        MarkoSpace.lg,
        MarkoSpace.md,
      ),
      decoration: BoxDecoration(
        color: colors.surfaceMuted.withValues(alpha: 0.5),
        border: Border(bottom: BorderSide(color: colors.border)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Container(
            width: 32,
            height: 32,
            decoration: BoxDecoration(
              color: colors.surfaceMuted,
              borderRadius: BorderRadius.circular(MarkoRadius.md),
              border: Border.all(color: colors.border),
            ),
            alignment: Alignment.center,
            child: HeroIcon(HeroIcons.bookOpen, size: 17, color: colors.ink),
          ),
          const SizedBox(width: MarkoSpace.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  'Як працює Marko',
                  style: Theme.of(context).textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.w600,
                    fontSize: 18,
                  ),
                ),
                const SizedBox(height: 1),
                Text(
                  'Короткий довідник з імпорту, пошуку та аналізу цін конкурентів',
                  style: MarkoType.caption.copyWith(color: colors.muted),
                ),
              ],
            ),
          ),
          const SizedBox(width: MarkoSpace.sm),
          IconButton(
            tooltip: 'Закрити',
            onPressed: () => Navigator.of(context).pop(),
            icon: const HeroIcon(HeroIcons.xMark, size: 18),
          ),
        ],
      ),
    );
  }

  Widget _buildTabs(MarkoTheme colors) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.symmetric(
        horizontal: MarkoSpace.lg,
        vertical: MarkoSpace.sm,
      ),
      child: Row(
        children: [
          for (final section in _HelpSection.values) ...[
            Padding(
              padding: const EdgeInsets.only(right: MarkoSpace.xs),
              child: ChoiceChip(
                selected: _active == section,
                showCheckmark: false,
                avatar: HeroIcon(
                  section.icon,
                  size: 14,
                  color: _active == section ? colors.brand : colors.muted,
                ),
                label: Text(
                  section.label,
                  style: TextStyle(
                    fontSize: 12.5,
                    fontWeight: _active == section
                        ? FontWeight.w600
                        : FontWeight.w500,
                    color: _active == section ? colors.ink : colors.muted,
                  ),
                ),
                backgroundColor: Colors.transparent,
                selectedColor: colors.brandSoft,
                side: BorderSide(
                  color: _active == section
                      ? colors.brand.withValues(alpha: 0.35)
                      : colors.border,
                ),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(999.0),
                ),
                onSelected: (_) => setState(() => _active = section),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildSection(BuildContext context, MarkoTheme colors) {
    return switch (_active) {
      _HelpSection.quickstart => _buildQuickstart(colors),
      _HelpSection.importCatalog => _buildImport(colors),
      _HelpSection.searchAndFilter => _buildSearch(colors),
      _HelpSection.competitors => _buildCompetitors(colors),
      _HelpSection.pricing => _buildPricing(colors),
    };
  }

  Widget _buildQuickstart(MarkoTheme colors) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _SectionBanner(
          colors: colors,
          icon: HeroIcons.bolt,
          title: '3 кроки для швидкого старту',
          description:
              'Завантажте асортимент один раз — Marko автоматично знайде ринкові пропозиції на авторинку України.',
        ),
        const SizedBox(height: MarkoSpace.lg),
        _GuideCard(
          number: '01',
          icon: HeroIcons.arrowDownTray,
          title: 'Завантажте каталог товарів',
          tag: 'Крок 1',
          body:
              'Експортуйте файл XLSX з Prom.ua або вкажіть пряме посилання на ваш магазин. Каталог обробиться за 1–2 хвилини.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.sm),
        _GuideCard(
          number: '02',
          icon: HeroIcons.magnifyingGlass,
          title: 'Знайдіть потрібну запчастину',
          tag: 'Крок 2',
          body:
              'Введіть будь-який OEM-номер, бренд або артикул у поле пошуку. Використовуйте фільтри діапазону цін у ₴.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.sm),
        _GuideCard(
          number: '03',
          icon: HeroIcons.presentationChartLine,
          title: 'Аналізуйте ціни конкурентів',
          tag: 'Крок 3',
          body:
              'Натисніть на товар у каталозі, щоб побачити мінімальну й медіанну ринкову ціну та список активних продавців на Avto.pro.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.md),
        _CalloutBox(
          colors: colors,
          icon: HeroIcons.informationCircle,
          text:
              'Швидка перевірка: кнопку «Ціни конкурентів» у шапці можна використовувати для швидкої перевірки будь-якого OEM без імпорту.',
        ),
      ],
    );
  }

  Widget _buildImport(MarkoTheme colors) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _SectionBanner(
          colors: colors,
          icon: HeroIcons.arrowDownTray,
          title: 'Імпорт та оновлення каталогу',
          description:
              'Як правильно експортувати товари та зберігати оригінальні номери для точного моніторингу.',
        ),
        const SizedBox(height: MarkoSpace.lg),
        _GuideCard(
          number: '01',
          icon: HeroIcons.documentText,
          title: 'Чому саме файл XLSX з Prom',
          tag: 'Рекомендовано',
          body:
              'Вивантаження Prom.ua у форматі XLSX містить окрему колонку з OEM-номерами деталей. Це гарантує 100% точний матчинг цін на Avto.pro.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.sm),
        _GuideCard(
          number: '02',
          icon: HeroIcons.globeAlt,
          title: 'Імпорт за посиланням на магазин',
          tag: 'Швидкий старт',
          body:
              'Якщо файлу немає під рукою, вкажіть URL вашого магазину Prom. Сервер автоматично збере назви, фотографії та поточні ціни.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.sm),
        _GuideCard(
          number: '03',
          icon: HeroIcons.arrowPath,
          title: 'Оновлення без дублікатів',
          tag: 'Синхронізація',
          body:
              'При повторному імпорті того ж файлу або магазину оновлюються лише ціни та наявність. Нові дублі товарів не створюються.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.md),
        _CalloutBox(
          colors: colors,
          icon: HeroIcons.informationCircle,
          text:
              'Інструкція Prom: Кабінет продавця -> розділ «Товари та послуги» -> кнопка «Експорт» -> формат XLSX.',
        ),
      ],
    );
  }

  Widget _buildSearch(MarkoTheme colors) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _SectionBanner(
          colors: colors,
          icon: HeroIcons.magnifyingGlass,
          title: 'Пошук, фільтрація та сортування',
          description:
              'Зручна робота з каталогом із тисячами товарних позицій.',
        ),
        const SizedBox(height: MarkoSpace.lg),
        _GuideCard(
          number: '01',
          icon: HeroIcons.bars3BottomLeft,
          title: 'Універсальний рядок пошуку',
          tag: 'Мульти-пошук',
          body:
              'Шукає одночасно за назвою деталі, брендом (Bosch, Valeo тощо), артикулом продавця (SKU) та всіма доступними OEM-кодами.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.sm),
        _GuideCard(
          number: '02',
          icon: HeroIcons.adjustmentsHorizontal,
          title: 'Фільтри цін у гривнях (₴)',
          tag: 'Цінові межі',
          body:
              'Введіть значення у поля «Ціна від» та «Ціна до». Каталог миттєво відфільтрує товари без перезавантаження сторінки.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.sm),
        _GuideCard(
          number: '03',
          icon: HeroIcons.arrowsUpDown,
          title: 'Липка панель при скролі',
          tag: 'Навігація',
          body:
              'Під час гортання списку товарів рядок пошуку та фільтри автоматично закріплюються у верхньому меню для швидкого доступу.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.md),
        _CalloutBox(
          colors: colors,
          icon: HeroIcons.informationCircle,
          text:
              'Порада: OEM-номери можна шукати як з дефісами та пробілами, так і суцільним текстом.',
        ),
      ],
    );
  }

  Widget _buildCompetitors(MarkoTheme colors) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _SectionBanner(
          colors: colors,
          icon: HeroIcons.presentationChartLine,
          title: 'Моніторинг цін на Avto.pro',
          description:
              'Як інтерпретувати ринкові пропозиції та цінові показники.',
        ),
        const SizedBox(height: MarkoSpace.lg),
        _GuideCard(
          number: '01',
          icon: HeroIcons.cpuChip,
          title: 'Матчинг за OEM-номерами',
          tag: 'Алгоритм',
          body:
              'Marko надсилає прямий запит на avto.pro за оригінальним номером деталі та формує повну цінову карту пропозицій продавців.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.sm),
        _GuideCard(
          number: '02',
          icon: HeroIcons.chartBar,
          title: 'Мінімальна vs Медіанна ціна',
          tag: 'Метрики',
          body:
              'Мінімальна ціна показує демпінгові пропозиції. Медіанна ціна відображає реальний ринковий рівень і захищена від штучних занижень.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.sm),
        _GuideCard(
          number: '03',
          icon: HeroIcons.clock,
          title: 'Історія та швидкий пошук',
          tag: 'Швидкий OEM',
          body:
              'Модал «Ціни конкурентів» зберігає останні пошуки, дозволяючи перевірити будь-який артикул або крос-номер в один клік.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.md),
        _CalloutBox(
          colors: colors,
          icon: HeroIcons.informationCircle,
          text:
              'Порада: Орієнтуйтеся саме на медіану ринку — це дозволяє утримувати високий прибуток без втрати замовлень.',
        ),
      ],
    );
  }

  Widget _buildPricing(MarkoTheme colors) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _SectionBanner(
          colors: colors,
          icon: HeroIcons.banknotes,
          title: 'Стратегії ціноутворення',
          description:
              'Як максимізувати маржу та не втрачати позиції в авторинку.',
        ),
        const SizedBox(height: MarkoSpace.lg),
        _GuideCard(
          number: '01',
          icon: HeroIcons.arrowTrendingUp,
          title: 'Медіанний ціновий коридор',
          tag: 'Маржинальність',
          body:
              'Не обов\'язково встановлювати найнижчу ціну на ринку. Встановлення ціни на рівні ринкової медіани зберігає на 10–15% більше маржі.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.sm),
        _GuideCard(
          number: '02',
          icon: HeroIcons.tag,
          title: 'Крос-коди та взаємозамінники',
          tag: 'Аналоги',
          body:
              'Якщо основний номер дефіцитний, перевіряйте супутні OEM-номери замінників — це допоможе знайти прибуткові вільні ніші.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.sm),
        _GuideCard(
          number: '03',
          icon: HeroIcons.devicePhoneMobile,
          title: 'Повна мобільна оптимізація',
          tag: 'Зручність',
          body:
              'Інтерфейс повністю адаптовано для смартфонів: картки, фільтри та детальні звіти відкриваються у зручному повноекранному форматі.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.md),
        _CalloutBox(
          colors: colors,
          icon: HeroIcons.informationCircle,
          text:
              'Порада: Перемикайте світлу/темну тему кнопкою у шапці — ваші налаштування автоматично зберігаються на пристрої.',
        ),
      ],
    );
  }

  Widget _buildFooter(BuildContext context, MarkoTheme colors, bool isCompact) {
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: isCompact ? MarkoSpace.md : MarkoSpace.xl,
        vertical: MarkoSpace.md,
      ),
      color: colors.surfaceMuted.withValues(alpha: 0.3),
      child: Row(
        children: [
          Expanded(
            child: Text(
              'Marko · Автоматична аналітика та ціноутворення',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: MarkoType.caption.copyWith(color: colors.faint),
            ),
          ),
          const SizedBox(width: MarkoSpace.md),
          MarkoButton(
            label: 'Зрозуміло',
            onPressed: () => Navigator.of(context).pop(),
          ),
        ],
      ),
    );
  }
}

class _SectionBanner extends StatelessWidget {
  const _SectionBanner({
    required this.colors,
    required this.icon,
    required this.title,
    required this.description,
  });

  final MarkoTheme colors;
  final HeroIcons icon;
  final String title;
  final String description;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(MarkoSpace.md),
      decoration: BoxDecoration(
        color: colors.surfaceMuted,
        borderRadius: BorderRadius.circular(MarkoRadius.md),
        border: Border.all(color: colors.border),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 28,
            height: 28,
            decoration: BoxDecoration(
              color: colors.surface,
              borderRadius: BorderRadius.circular(MarkoRadius.sm),
              border: Border.all(color: colors.border),
            ),
            alignment: Alignment.center,
            child: HeroIcon(icon, size: 15, color: colors.ink),
          ),
          const SizedBox(width: MarkoSpace.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: Theme.of(
                    context,
                  ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 2),
                Text(
                  description,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: colors.muted,
                    height: 1.35,
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

class _GuideCard extends StatelessWidget {
  const _GuideCard({
    required this.number,
    required this.icon,
    required this.title,
    required this.tag,
    required this.body,
    required this.colors,
  });

  final String number;
  final HeroIcons icon;
  final String title;
  final String tag;
  final String body;
  final MarkoTheme colors;

  @override
  Widget build(BuildContext context) {
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
            width: 28,
            height: 28,
            decoration: BoxDecoration(
              color: colors.surfaceMuted,
              borderRadius: BorderRadius.circular(MarkoRadius.sm),
              border: Border.all(color: colors.border),
            ),
            alignment: Alignment.center,
            child: Text(
              number,
              style: MarkoType.caption.copyWith(
                color: colors.ink,
                fontWeight: FontWeight.w700,
                fontSize: 11,
              ),
            ),
          ),
          const SizedBox(width: MarkoSpace.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Wrap(
                  spacing: MarkoSpace.sm,
                  runSpacing: 2,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text(
                      title,
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: MarkoSpace.xs,
                        vertical: 1,
                      ),
                      decoration: BoxDecoration(
                        color: colors.surfaceMuted,
                        borderRadius: BorderRadius.circular(MarkoRadius.xs),
                        border: Border.all(color: colors.border),
                      ),
                      child: Text(
                        tag,
                        style: MarkoType.caption.copyWith(
                          fontSize: 10.5,
                          color: colors.faint,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 3),
                Text(
                  body,
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

class _CalloutBox extends StatelessWidget {
  const _CalloutBox({
    required this.colors,
    required this.icon,
    required this.text,
  });

  final MarkoTheme colors;
  final HeroIcons icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(MarkoSpace.md),
      decoration: BoxDecoration(
        color: colors.surfaceMuted,
        borderRadius: BorderRadius.circular(MarkoRadius.md),
        border: Border.all(color: colors.border),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          HeroIcon(icon, size: 16, color: colors.muted),
          const SizedBox(width: MarkoSpace.sm),
          Expanded(
            child: Text(
              text,
              style: TextStyle(fontSize: 12, color: colors.muted, height: 1.4),
            ),
          ),
        ],
      ),
    );
  }
}
