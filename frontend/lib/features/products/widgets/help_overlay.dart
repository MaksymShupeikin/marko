import 'package:flutter/material.dart';
import 'package:heroicons/heroicons.dart';

import '../../../core/app_theme.dart';

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
  searchAndFilter('Пошук & Фільтри', HeroIcons.magnifyingGlass),
  competitors('Ціни Avto.pro', HeroIcons.presentationChartLine),
  management('Керування товарами', HeroIcons.adjustmentsHorizontal);

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
        constraints: const BoxConstraints(maxWidth: 780, maxHeight: 740),
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
            padding: EdgeInsets.all(isCompact ? MarkoSpace.lg : MarkoSpace.xl),
            child: _buildSection(context, colors),
          ),
        ),
      ],
    );
  }

  Widget _buildHeader(BuildContext context, MarkoTheme colors) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(
        MarkoSpace.xl,
        MarkoSpace.lg,
        MarkoSpace.md,
        MarkoSpace.md,
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Expanded(
            child: Text(
              'Інструкція',
              style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          const SizedBox(width: MarkoSpace.md),
          IconButton(
            tooltip: 'Закрити',
            onPressed: () => Navigator.of(context).pop(),
            icon: const HeroIcon(HeroIcons.xMark, size: 20),
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
                backgroundColor: colors.surfaceMuted,
                selectedColor: colors.brandSoft,
                side: BorderSide(
                  color: _active == section
                      ? colors.brand.withValues(alpha: 0.35)
                      : colors.border,
                ),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(MarkoRadius.md),
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
      _HelpSection.management => _buildManagement(colors),
    };
  }

  Widget _buildQuickstart(MarkoTheme colors) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _SectionHeader(
          title: '3 простих кроки для початку роботи',
          description:
              'Marko автоматизує обробку каталогу та моніторинг ринкових цін на автозапчастини в Україні.',
        ),
        const SizedBox(height: MarkoSpace.md),
        _GuideCard(
          number: '01',
          icon: HeroIcons.arrowDownTray,
          title: 'Імпортуйте товари в каталог',
          body:
              'Завантажте XLSX-файл експорту з кабінету Prom.ua або вкажіть пряме посилання на ваш магазин. Сервер обробить асортимент за 1–2 хвилини.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.sm),
        _GuideCard(
          number: '02',
          icon: HeroIcons.magnifyingGlass,
          title: 'Зручний пошук та фільтри',
          body:
              'Шукайте за OEM-номерами, брендом, артикулом або назвою. Використовуйте фільтри цінового коридору в ₴ та перемикач джерел.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.sm),
        _GuideCard(
          number: '03',
          icon: HeroIcons.presentationChartLine,
          title: 'Аналітика цін на Avto.pro',
          body:
              'Клікніть на будь-який товар або скористайтесь кнопкою «Ціни конкурентів» у шапці, щоб побачити спред ринку (мін/медіана/макс) та всі активні пропозиції.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.md),
        _CalloutBox(
          colors: colors,
          icon: HeroIcons.lightBulb,
          text:
              'Порада: Швидкий OEM-пошук у шапці працює автономно — ви можете перевіряти будь-які артикули навіть без попереднього імпорту.',
        ),
      ],
    );
  }

  Widget _buildImport(MarkoTheme colors) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _SectionHeader(
          title: 'Імпорт та синхронізація каталогу',
          description:
              'Як завантажувати товари та забезпечити точний автоматичний матчинг цін.',
        ),
        const SizedBox(height: MarkoSpace.md),
        _GuideCard(
          number: '01',
          icon: HeroIcons.documentText,
          title: 'Експорт файлу XLSX з Prom.ua',
          body:
              'Файл експорту містить оригінальні номери OEM та артикули виробників у відповідних колонках, що гарантує 100% точний матчинг на Avto.pro.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.sm),
        _GuideCard(
          number: '02',
          icon: HeroIcons.globeAlt,
          title: 'Прямий імпорт за посиланням на магазин',
          body:
              'Вкажіть URL вашого магазину Prom.ua. Marko автоматично завантажить назви позицій, фотографії, наявність та поточні ціни.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.sm),
        _GuideCard(
          number: '03',
          icon: HeroIcons.arrowPath,
          title: 'Жива панель синхронізації (Dynamic Island)',
          body:
              'Хід імпорту відображається у плаваючій панелі зверху з одометром кількості товарів. Нові позиції плавно з\'являються в каталозі в реальному часі.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.md),
        _CalloutBox(
          colors: colors,
          icon: HeroIcons.lightBulb,
          text:
              'Де завантажити файл: Кабінет Prom.ua -> «Товари та послуги» -> кнопка «Експорт» -> виберіть формат XLSX.',
        ),
      ],
    );
  }

  Widget _buildSearch(MarkoTheme colors) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _SectionHeader(
          title: 'Пошук, фільтри та сортування',
          description:
              'Миттєва робота з великими каталогами без перезавантаження сторінки.',
        ),
        const SizedBox(height: MarkoSpace.md),
        _GuideCard(
          number: '01',
          icon: HeroIcons.bars3BottomLeft,
          title: 'Розумний мульти-пошук',
          body:
              'Рядок пошуку одночасно шукає за назвою товару, брендом виробника (Bosch, VAG, Valeo), внутрішнім SKU та будь-якими OEM-кодами запчастини.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.sm),
        _GuideCard(
          number: '02',
          icon: HeroIcons.adjustmentsHorizontal,
          title: 'Фільтри цінового діапазону у ₴',
          body:
              'Вказуйте межі «Ціна від» та «Ціна до». Каталог миттєво відсікає зайві позиції з плавною анімацією завантаження.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.sm),
        _GuideCard(
          number: '03',
          icon: HeroIcons.funnel,
          title: 'Перемикач джерела та сортування',
          body:
              'Фільтруйте товари за джерелом («Всі», «Prom.ua», «Ручні») та сортуйте за зростанням або спаданням ціни чи алфавітом.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.md),
        _CalloutBox(
          colors: colors,
          icon: HeroIcons.lightBulb,
          text:
              'Порада: OEM-номери можна вводити у будь-якому форматі — пробіли та спецсимволи обробляються автоматично.',
        ),
      ],
    );
  }

  Widget _buildCompetitors(MarkoTheme colors) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _SectionHeader(
          title: 'Моніторинг ринку на Avto.pro',
          description:
              'Аналітика цін продавців, спред ринку та визначення оптимальної вартості.',
        ),
        const SizedBox(height: MarkoSpace.md),
        _GuideCard(
          number: '01',
          icon: HeroIcons.chartBar,
          title: 'Кольоровий спектр ринкових цін',
          body:
              'Градієнтна шкала наочно показує мінімальну, медіанну та максимальну ціну ринку, а також точне положення вашої ціни відносно конкурентів.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.sm),
        _GuideCard(
          number: '02',
          icon: HeroIcons.buildingStorefront,
          title: 'Детальний список пропозицій конкурентів',
          body:
              'Переглядайте актуальних продавців на Avto.pro: назву магазину, місто знаходження, термін доставки та відсоток різниці з вашою ціною.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.sm),
        _GuideCard(
          number: '03',
          icon: HeroIcons.bolt,
          title: 'Орієнтація на медіану ринку',
          body:
              'Мінімальна ціна часто є демпінговою або містить приховані умови. Встановлення ціни на рівні ринкової медіани максимізує маржу без втрати продажів.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.md),
        _CalloutBox(
          colors: colors,
          icon: HeroIcons.lightBulb,
          text:
              'Швидкий доступ: Перевіряйте історію останніх OEM-запитів у вікні «Ціни конкурентів» в один клік.',
        ),
      ],
    );
  }

  Widget _buildManagement(MarkoTheme colors) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _SectionHeader(
          title: 'Керування та масові операції',
          description:
              'Інструменти для швидкого оновлення та редагування каталогу товарів.',
        ),
        const SizedBox(height: MarkoSpace.md),
        _GuideCard(
          number: '01',
          icon: HeroIcons.checkBadge,
          title: 'Масовий вибір товарів',
          body:
              'Виділяйте окремі картки чекбоксами або обирайте всі товари поточної вибірки фільтра в один клік через плаваючу панель вибору.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.sm),
        _GuideCard(
          number: '02',
          icon: HeroIcons.arrowPath,
          title: 'Пакетне оновлення та видалення',
          body:
              'Оновлюйте актуальні ціни з Prom.ua або видаляйте застарілі позиції пакетами безпосередньо через сервер Marko.',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.sm),
        _GuideCard(
          number: '03',
          icon: HeroIcons.pencilSquare,
          title: 'Ручне редагування та створення',
          body:
              'Редагуйте назву, бренд, OEM-номери та ціну будь-якого товару через бічну панель або додавайте нові позиції через кнопку «Додати товар».',
          colors: colors,
        ),
        const SizedBox(height: MarkoSpace.md),
        _CalloutBox(
          colors: colors,
          icon: HeroIcons.lightBulb,
          text:
              'Зручність: Тема інтерфейсу (світла/темна) автоматично запам\'ятовується для вашого облікового запису на всіх пристроях.',
        ),
      ],
    );
  }
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader({
    required this.title,
    required this.description,
  });

  final String title;
  final String description;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: MarkoSpace.xs),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: Theme.of(context).textTheme.titleLarge?.copyWith(
              fontWeight: FontWeight.w600,
              fontSize: 17.5,
              letterSpacing: -0.2,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            description,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: colors.muted,
              height: 1.4,
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
    required this.body,
    required this.colors,
  });

  final String number;
  final HeroIcons icon;
  final String title;
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
                Text(
                  title,
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w600,
                  ),
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
    final isDark = Theme.of(context).brightness == Brightness.dark;
    const amber = Color(0xFFF59E0B);
    final bg = isDark
        ? amber.withValues(alpha: 0.09)
        : const Color(0xFFFFFBEB);
    final border = isDark
        ? amber.withValues(alpha: 0.26)
        : const Color(0xFFFDE68A);
    final iconColor = isDark ? const Color(0xFFFBBF24) : const Color(0xFFD97706);
    final textColor = isDark ? colors.ink : const Color(0xFF92400E);

    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: MarkoSpace.md,
        vertical: 11,
      ),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(MarkoRadius.md),
        border: Border.all(color: border),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          HeroIcon(icon, size: 17, color: iconColor),
          const SizedBox(width: MarkoSpace.sm),
          Expanded(
            child: Text(
              text,
              style: TextStyle(
                fontSize: 12.5,
                color: textColor,
                height: 1.42,
                fontWeight: FontWeight.w500,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
