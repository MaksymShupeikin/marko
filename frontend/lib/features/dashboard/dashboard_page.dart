import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/app_language.dart';
import '../../core/app_theme.dart';
import '../../core/marko_ui.dart';
import '../../core/widgets/marko_button.dart';
import '../../core/widgets/marko_menu.dart';
import '../auth/auth_controller.dart';
import '../catalog/catalog_page.dart';
import '../pricing/recommendations_page.dart';
import '../stores/stores_controller.dart';
import '../stores/stores_page.dart';

class DashboardPage extends ConsumerStatefulWidget {
  const DashboardPage({super.key});

  @override
  ConsumerState<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends ConsumerState<DashboardPage> {
  int _selectedIndex = 0;

  @override
  Widget build(BuildContext context) {
    final user = ref.watch(authControllerProvider).value?.user;
    final language = ref.watch(appLanguageProvider);
    final destinations = <_Destination>[
      _Destination(
        Icons.price_check_rounded,
        context.localized(ru: 'Сравнение цен', uk: 'Порівняння цін'),
      ),
      _Destination(
        Icons.inventory_2_outlined,
        context.localized(ru: 'Каталог', uk: 'Каталог'),
      ),
      _Destination(
        Icons.store_mall_directory_outlined,
        context.localized(ru: 'Мои магазины', uk: 'Мої магазини'),
      ),
      _Destination(
        Icons.grid_view_rounded,
        context.localized(ru: 'Обзор', uk: 'Огляд'),
      ),
    ];
    final content = switch (_selectedIndex) {
      1 => CatalogPage(onOpenPriceComparison: () => _select(0)),
      2 => const StoresPage(ownedOnly: true),
      3 => _Overview(onOpenStores: () => _select(2)),
      _ => RecommendationsPage(onOpenCatalog: () => _select(1)),
    };

    return Scaffold(
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) {
            final wide = constraints.maxWidth >= 900;
            if (wide) {
              return Row(
                children: [
                  _Sidebar(
                    destinations: destinations,
                    selectedIndex: _selectedIndex,
                    email: user?.email,
                    language: language,
                    onSelected: _select,
                    onLanguageSelected: _selectLanguage,
                    onLogout: _logout,
                  ),
                  Expanded(
                    child: Column(
                      children: [
                        _PageBar(title: destinations[_selectedIndex].label),
                        Expanded(child: content),
                      ],
                    ),
                  ),
                ],
              );
            }
            return Column(
              children: [
                _MobileHeader(
                  language: language,
                  onLanguageSelected: _selectLanguage,
                  onLogout: _logout,
                ),
                Expanded(child: content),
                _MobileNavigation(
                  destinations: destinations,
                  selectedIndex: _selectedIndex,
                  onSelected: _select,
                ),
              ],
            );
          },
        ),
      ),
    );
  }

  void _select(int index) => setState(() => _selectedIndex = index);

  void _selectLanguage(AppLanguage language) =>
      ref.read(appLanguageProvider.notifier).select(language);

  void _logout() => ref.read(authControllerProvider.notifier).logout();
}

class _Destination {
  const _Destination(this.icon, this.label);

  final IconData icon;
  final String label;
}

class _Sidebar extends StatelessWidget {
  const _Sidebar({
    required this.destinations,
    required this.selectedIndex,
    required this.email,
    required this.language,
    required this.onSelected,
    required this.onLanguageSelected,
    required this.onLogout,
  });

  final List<_Destination> destinations;
  final int selectedIndex;
  final String? email;
  final AppLanguage language;
  final ValueChanged<int> onSelected;
  final ValueChanged<AppLanguage> onLanguageSelected;
  final VoidCallback onLogout;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      width: 236,
      decoration: BoxDecoration(
        color: colors.surface,
        border: Border(right: BorderSide(color: colors.border)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Padding(
            padding: EdgeInsets.fromLTRB(24, 23, 24, 30),
            child: MarkoWordmark(),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: Text(
              context.localized(ru: 'РАБОЧАЯ ОБЛАСТЬ', uk: 'РОБОЧА ОБЛАСТЬ'),
              style: Theme.of(context).textTheme.labelMedium,
            ),
          ),
          const SizedBox(height: 10),
          ...List.generate(
            destinations.length,
            (index) => _SidebarItem(
              destination: destinations[index],
              selected: index == selectedIndex,
              onTap: () => onSelected(index),
            ),
          ),
          const Spacer(),
          Container(
            decoration: BoxDecoration(
              border: Border(top: BorderSide(color: colors.border)),
            ),
            child: Column(
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(12, 12, 12, 10),
                  child: _LanguageSelector(
                    language: language,
                    onSelected: onLanguageSelected,
                  ),
                ),
                Divider(color: colors.border),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 12, 12, 14),
                  child: Row(
                    children: [
                      Container(
                        width: 34,
                        height: 34,
                        decoration: BoxDecoration(
                          color: colors.surfaceMuted,
                          borderRadius: BorderRadius.circular(9),
                        ),
                        alignment: Alignment.center,
                        child: Icon(
                          Icons.person_outline_rounded,
                          size: 18,
                          color: colors.muted,
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          email ??
                              context.localized(
                                ru: 'Аккаунт Marko',
                                uk: 'Обліковий запис Marko',
                              ),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context).textTheme.bodySmall
                              ?.copyWith(
                                color: colors.ink,
                                fontWeight: FontWeight.w500,
                              ),
                        ),
                      ),
                      IconButton(
                        tooltip: context.localized(ru: 'Выйти', uk: 'Вийти'),
                        onPressed: onLogout,
                        icon: const Icon(Icons.logout_rounded, size: 18),
                      ),
                    ],
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

class _LanguageSelector extends StatelessWidget {
  const _LanguageSelector({
    required this.language,
    required this.onSelected,
    this.compact = false,
  });

  final AppLanguage language;
  final ValueChanged<AppLanguage> onSelected;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return MarkoMenuButton<AppLanguage>(
      key: const ValueKey('language-selector'),
      tooltip: context.localized(ru: 'Выбрать язык', uk: 'Обрати мову'),
      header: context.localized(ru: 'Язык интерфейса', uk: 'Мова інтерфейсу'),
      selected: language,
      onSelected: onSelected,
      minWidth: 220,
      offset: const Offset(0, -12),
      entries: AppLanguage.values
          .map(
            (item) => MarkoMenuEntry(
              value: item,
              label: item.nativeLabel,
              avatarText: item.shortLabel,
            ),
          )
          .toList(growable: false),
      child: Container(
        width: compact ? null : double.infinity,
        padding: EdgeInsets.symmetric(
          horizontal: compact ? 9 : 11,
          vertical: 9,
        ),
        decoration: BoxDecoration(
          color: colors.surfaceMuted,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: colors.border),
        ),
        child: Row(
          mainAxisSize: compact ? MainAxisSize.min : MainAxisSize.max,
          children: [
            Icon(Icons.language_rounded, size: 18, color: colors.muted),
            const SizedBox(width: 9),
            if (!compact)
              Expanded(
                child: Text(
                  language.nativeLabel,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: colors.ink,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            if (compact)
              Text(
                language.shortLabel,
                style: Theme.of(
                  context,
                ).textTheme.labelMedium?.copyWith(color: colors.ink),
              ),
            const SizedBox(width: 5),
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

class _SidebarItem extends StatelessWidget {
  const _SidebarItem({
    required this.destination,
    required this.selected,
    required this.onTap,
  });

  final _Destination destination;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 3),
      child: Material(
        color: selected ? colors.brandSoft : Colors.transparent,
        borderRadius: BorderRadius.circular(8),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(8),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
            child: Row(
              children: [
                Icon(
                  destination.icon,
                  size: 19,
                  color: selected ? colors.brand : colors.muted,
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    destination.label,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: selected ? colors.brand : colors.ink,
                      fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _PageBar extends StatelessWidget {
  const _PageBar({required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      height: 72,
      padding: const EdgeInsets.symmetric(horizontal: 32),
      decoration: BoxDecoration(
        color: colors.surface,
        border: Border(bottom: BorderSide(color: colors.border)),
      ),
      child: Row(
        children: [
          Text(title, style: Theme.of(context).textTheme.titleLarge),
          const Spacer(),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: colors.positiveSoft,
              borderRadius: BorderRadius.circular(7),
            ),
            child: Row(
              children: [
                Container(
                  width: 6,
                  height: 6,
                  decoration: BoxDecoration(
                    color: colors.positive,
                    shape: BoxShape.circle,
                  ),
                ),
                const SizedBox(width: 7),
                Text(
                  context.localized(
                    ru: 'Система активна',
                    uk: 'Система активна',
                  ),
                  style: Theme.of(
                    context,
                  ).textTheme.labelMedium?.copyWith(color: colors.positive),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _MobileHeader extends StatelessWidget {
  const _MobileHeader({
    required this.language,
    required this.onLanguageSelected,
    required this.onLogout,
  });

  final AppLanguage language;
  final ValueChanged<AppLanguage> onLanguageSelected;
  final VoidCallback onLogout;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      height: 64,
      padding: const EdgeInsets.symmetric(horizontal: 18),
      decoration: BoxDecoration(
        color: colors.surface,
        border: Border(bottom: BorderSide(color: colors.border)),
      ),
      child: Row(
        children: [
          const MarkoWordmark(compact: true),
          const Spacer(),
          _LanguageSelector(
            language: language,
            onSelected: onLanguageSelected,
            compact: true,
          ),
          const SizedBox(width: 6),
          IconButton(
            tooltip: context.localized(ru: 'Выйти', uk: 'Вийти'),
            onPressed: onLogout,
            icon: const Icon(Icons.logout_rounded, size: 19),
          ),
        ],
      ),
    );
  }
}

class _MobileNavigation extends StatelessWidget {
  const _MobileNavigation({
    required this.destinations,
    required this.selectedIndex,
    required this.onSelected,
  });

  final List<_Destination> destinations;
  final int selectedIndex;
  final ValueChanged<int> onSelected;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      padding: const EdgeInsets.fromLTRB(8, 8, 8, 10),
      decoration: BoxDecoration(
        color: colors.surface,
        border: Border(top: BorderSide(color: colors.border)),
      ),
      child: Row(
        children: List.generate(destinations.length, (index) {
          final selected = selectedIndex == index;
          final item = destinations[index];
          return Expanded(
            child: InkWell(
              onTap: () => onSelected(index),
              borderRadius: BorderRadius.circular(8),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      item.icon,
                      size: 20,
                      color: selected ? colors.brand : colors.muted,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      item.label,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.labelMedium?.copyWith(
                        color: selected ? colors.brand : colors.muted,
                        fontSize: 10.5,
                        letterSpacing: -0.1,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          );
        }),
      ),
    );
  }
}

class _Overview extends ConsumerWidget {
  const _Overview({required this.onOpenStores});

  final VoidCallback onOpenStores;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final stores = ref.watch(storesControllerProvider).value?.stores;
    final storeCount = stores?.length;
    final productCount = stores?.fold<int>(
      0,
      (total, store) => total + store.productCount,
    );
    final syncedCount = stores
        ?.where((store) => store.lastSyncedAt != null)
        .length;
    final colors = MarkoTheme.of(context);

    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 28),
      children: [
        Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1120),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Wrap(
                  alignment: WrapAlignment.spaceBetween,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  spacing: 20,
                  runSpacing: 16,
                  children: [
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          context.localized(
                            ru: 'Цены под контролем',
                            uk: 'Ціни під контролем',
                          ),
                          style: Theme.of(context).textTheme.headlineMedium,
                        ),
                        const SizedBox(height: 7),
                        Text(
                          context.localized(
                            ru: 'Единая картина по магазинам, товарам и конкурентам.',
                            uk: 'Єдина картина за магазинами, товарами й конкурентами.',
                          ),
                          style: Theme.of(
                            context,
                          ).textTheme.bodyMedium?.copyWith(color: colors.muted),
                        ),
                      ],
                    ),
                    MarkoButton(
                      label: context.localized(
                        ru: 'Подключить магазин',
                        uk: 'Підключити магазин',
                      ),
                      onPressed: onOpenStores,
                      icon: Icons.add_rounded,
                    ),
                  ],
                ),
                const SizedBox(height: 28),
                LayoutBuilder(
                  builder: (context, constraints) {
                    final columns = constraints.maxWidth >= 760 ? 3 : 1;
                    final width = columns == 3
                        ? (constraints.maxWidth - 32) / 3
                        : constraints.maxWidth;
                    return Wrap(
                      spacing: 16,
                      runSpacing: 16,
                      children: [
                        _MetricPanel(
                          width: width,
                          icon: Icons.storefront_outlined,
                          value: storeCount?.toString() ?? '—',
                          label: context.localized(
                            ru: 'Подключено магазинов',
                            uk: 'Підключено магазинів',
                          ),
                        ),
                        _MetricPanel(
                          width: width,
                          icon: Icons.inventory_2_outlined,
                          value: productCount?.toString() ?? '—',
                          label: context.localized(
                            ru: 'Товаров в мониторинге',
                            uk: 'Товарів у моніторингу',
                          ),
                        ),
                        _MetricPanel(
                          width: width,
                          icon: Icons.check_circle_outline_rounded,
                          value: syncedCount?.toString() ?? '—',
                          label: context.localized(
                            ru: 'Синхронизировано',
                            uk: 'Синхронізовано',
                          ),
                          positive: true,
                        ),
                      ],
                    );
                  },
                ),
                const SizedBox(height: 20),
                MarkoPanel(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        context.localized(
                          ru: 'Как работает Marko',
                          uk: 'Як працює Marko',
                        ),
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                      const SizedBox(height: 6),
                      Text(
                        context.localized(
                          ru: 'Три шага до понятной картины рынка.',
                          uk: 'Три кроки до зрозумілої картини ринку.',
                        ),
                        style: Theme.of(
                          context,
                        ).textTheme.bodyMedium?.copyWith(color: colors.muted),
                      ),
                      const SizedBox(height: 24),
                      const _WorkflowSteps(),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _MetricPanel extends StatelessWidget {
  const _MetricPanel({
    required this.width,
    required this.icon,
    required this.value,
    required this.label,
    this.positive = false,
  });

  final double width;
  final IconData icon;
  final String value;
  final String label;
  final bool positive;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final accent = positive ? colors.positive : colors.brand;
    final accentSoft = positive ? colors.positiveSoft : colors.brandSoft;
    return SizedBox(
      width: width,
      child: MarkoPanel(
        padding: const EdgeInsets.all(20),
        child: Row(
          children: [
            Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(
                color: accentSoft,
                borderRadius: BorderRadius.circular(9),
              ),
              alignment: Alignment.center,
              child: Icon(icon, color: accent, size: 20),
            ),
            const SizedBox(width: 15),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(value, style: Theme.of(context).textTheme.headlineSmall),
                  const SizedBox(height: 2),
                  Text(label, style: Theme.of(context).textTheme.bodySmall),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _WorkflowSteps extends StatelessWidget {
  const _WorkflowSteps();

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final horizontal = constraints.maxWidth >= 700;
        final steps = [
          _WorkflowStep(
            number: '01',
            title: context.localized(
              ru: 'Подключите магазин',
              uk: 'Підключіть магазин',
            ),
            description: context.localized(
              ru: 'Добавьте ссылку Prom — каталог импортируется автоматически.',
              uk: 'Додайте посилання Prom — каталог імпортується автоматично.',
            ),
          ),
          _WorkflowStep(
            number: '02',
            title: context.localized(
              ru: 'Найдите конкурентов',
              uk: 'Знайдіть конкурентів',
            ),
            description: context.localized(
              ru: 'Marko сопоставит похожие позиции и соберёт цены.',
              uk: 'Marko зіставить схожі позиції та збере ціни.',
            ),
          ),
          _WorkflowStep(
            number: '03',
            title: context.localized(
              ru: 'Управляйте ценой',
              uk: 'Керуйте ціною',
            ),
            description: context.localized(
              ru: 'Сравнивайте предложения и замечайте изменения рынка.',
              uk: 'Порівнюйте пропозиції та помічайте зміни ринку.',
            ),
          ),
        ];
        if (!horizontal) {
          return Column(
            children: [
              steps[0],
              SizedBox(height: 22),
              steps[1],
              SizedBox(height: 22),
              steps[2],
            ],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(child: steps[0]),
            SizedBox(width: 28),
            Expanded(child: steps[1]),
            SizedBox(width: 28),
            Expanded(child: steps[2]),
          ],
        );
      },
    );
  }
}

class _WorkflowStep extends StatelessWidget {
  const _WorkflowStep({
    required this.number,
    required this.title,
    required this.description,
  });

  final String number;
  final String title;
  final String description;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          number,
          style: Theme.of(
            context,
          ).textTheme.labelLarge?.copyWith(color: colors.brand),
        ),
        const SizedBox(width: 13),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 5),
              Text(description, style: Theme.of(context).textTheme.bodySmall),
            ],
          ),
        ),
      ],
    );
  }
}
