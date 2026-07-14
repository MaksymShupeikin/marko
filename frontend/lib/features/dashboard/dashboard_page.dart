import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/app_theme.dart';
import '../../core/marko_ui.dart';
import '../../core/widgets/marko_button.dart';
import '../auth/auth_controller.dart';
import '../stores/stores_controller.dart';
import '../stores/stores_page.dart';

class DashboardPage extends ConsumerStatefulWidget {
  const DashboardPage({super.key});

  @override
  ConsumerState<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends ConsumerState<DashboardPage> {
  int _selectedIndex = 0;

  static const _destinations = <_Destination>[
    _Destination(Icons.grid_view_rounded, 'Обзор'),
    _Destination(Icons.storefront_outlined, 'Магазины'),
    _Destination(Icons.inventory_2_outlined, 'Товары'),
  ];

  @override
  Widget build(BuildContext context) {
    final user = ref.watch(authControllerProvider).value?.user;
    final content = switch (_selectedIndex) {
      1 => const StoresPage(),
      2 => _ProductsStart(onOpenStores: () => _select(1)),
      _ => _Overview(onOpenStores: () => _select(1)),
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
                    destinations: _destinations,
                    selectedIndex: _selectedIndex,
                    email: user?.email,
                    onSelected: _select,
                    onLogout: _logout,
                  ),
                  Expanded(
                    child: Column(
                      children: [
                        _PageBar(title: _destinations[_selectedIndex].label),
                        Expanded(child: content),
                      ],
                    ),
                  ),
                ],
              );
            }
            return Column(
              children: [
                _MobileHeader(onLogout: _logout),
                Expanded(child: content),
                _MobileNavigation(
                  destinations: _destinations,
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
    required this.onSelected,
    required this.onLogout,
  });

  final List<_Destination> destinations;
  final int selectedIndex;
  final String? email;
  final ValueChanged<int> onSelected;
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
              'РАБОЧАЯ ОБЛАСТЬ',
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
            padding: const EdgeInsets.fromLTRB(16, 16, 12, 16),
            decoration: BoxDecoration(
              border: Border(top: BorderSide(color: colors.border)),
            ),
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
                    email ?? 'Аккаунт Marko',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: colors.ink,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ),
                IconButton(
                  tooltip: 'Выйти',
                  onPressed: onLogout,
                  icon: const Icon(Icons.logout_rounded, size: 18),
                ),
              ],
            ),
          ),
        ],
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
                Text(
                  destination.label,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: selected ? colors.brand : colors.ink,
                    fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
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
                  'Система активна',
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
  const _MobileHeader({required this.onLogout});

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
          IconButton(
            tooltip: 'Выйти',
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
                      style: Theme.of(context).textTheme.labelMedium?.copyWith(
                        color: selected ? colors.brand : colors.muted,
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
                          'Цены под контролем',
                          style: Theme.of(context).textTheme.headlineMedium,
                        ),
                        const SizedBox(height: 7),
                        Text(
                          'Единая картина по магазинам, товарам и конкурентам.',
                          style: Theme.of(
                            context,
                          ).textTheme.bodyMedium?.copyWith(color: colors.muted),
                        ),
                      ],
                    ),
                    MarkoButton(
                      label: 'Подключить магазин',
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
                          label: 'Подключено магазинов',
                        ),
                        _MetricPanel(
                          width: width,
                          icon: Icons.inventory_2_outlined,
                          value: productCount?.toString() ?? '—',
                          label: 'Товаров в мониторинге',
                        ),
                        _MetricPanel(
                          width: width,
                          icon: Icons.check_circle_outline_rounded,
                          value: syncedCount?.toString() ?? '—',
                          label: 'Синхронизировано',
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
                        'Как работает Marko',
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                      const SizedBox(height: 6),
                      Text(
                        'Три шага до понятной картины рынка.',
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
        const steps = [
          _WorkflowStep(
            number: '01',
            title: 'Подключите магазин',
            description:
                'Добавьте ссылку Prom — каталог импортируется автоматически.',
          ),
          _WorkflowStep(
            number: '02',
            title: 'Найдите конкурентов',
            description: 'Marko сопоставит похожие позиции и соберёт цены.',
          ),
          _WorkflowStep(
            number: '03',
            title: 'Управляйте ценой',
            description: 'Сравнивайте предложения и замечайте изменения рынка.',
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

class _ProductsStart extends StatelessWidget {
  const _ProductsStart({required this.onOpenStores});

  final VoidCallback onOpenStores;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: MarkoPanel(
            padding: const EdgeInsets.all(32),
            child: Column(
              children: [
                Container(
                  width: 48,
                  height: 48,
                  decoration: BoxDecoration(
                    color: colors.brandSoft,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Icon(Icons.inventory_2_outlined, color: colors.brand),
                ),
                const SizedBox(height: 18),
                Text(
                  'Выберите магазин',
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 8),
                Text(
                  'Откройте подключённый магазин, чтобы посмотреть его каталог.',
                  textAlign: TextAlign.center,
                  style: Theme.of(
                    context,
                  ).textTheme.bodyMedium?.copyWith(color: colors.muted),
                ),
                const SizedBox(height: 22),
                MarkoButton(
                  label: 'Перейти к магазинам',
                  onPressed: onOpenStores,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
