import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/app_language.dart';
import '../../core/app_theme.dart';
import '../../core/app_theme_mode.dart';
import '../../core/marko_motion.dart';
import '../../core/marko_ui.dart';
import '../../core/system_status.dart';
import '../../core/widgets/marko_atmosphere.dart';
import '../../core/widgets/marko_menu.dart';
import '../auth/auth_controller.dart';
import '../attention/attention_controller.dart';
import '../attention/attention_page.dart';
import '../catalog/catalog_controller.dart';
import '../catalog/catalog_import_dialog.dart';
import '../catalog/catalog_page.dart';
import '../pricing/recommendations_page.dart';
import '../stores/stores_page.dart';

class DashboardPage extends ConsumerStatefulWidget {
  const DashboardPage({
    this.initialTab = 0,
    this.initialCatalogProductId,
    this.initialRecommendationId,
    this.legacyPricing = false,
    this.routeNavigation = false,
    super.key,
  });

  final int initialTab;
  final String? initialCatalogProductId;
  final String? initialRecommendationId;
  final bool legacyPricing;
  final bool routeNavigation;

  @override
  ConsumerState<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends ConsumerState<DashboardPage> {
  static const _catalogIndex = 1;
  static const _storesIndex = 2;

  late int _selectedIndex;
  late final Set<int> _visitedTabs;
  String? _catalogStoreId;

  @override
  void initState() {
    super.initState();
    _selectedIndex = widget.initialCatalogProductId != null
        ? _catalogIndex
        : widget.initialRecommendationId != null
        ? 0
        : widget.initialTab.clamp(0, 2);
    _visitedTabs = {_selectedIndex};
  }

  @override
  Widget build(BuildContext context) {
    final user = ref.watch(authControllerProvider).value?.user;
    final canAdministerWorkspace = user?.canAdministerWorkspace ?? false;
    final language = ref.watch(appLanguageProvider);
    final destinations = <DashboardDestination>[
      DashboardDestination(
        Icons.notification_important_outlined,
        context.localized(ru: 'Требует внимания', uk: 'Потребує уваги'),
      ),
      DashboardDestination(
        Icons.inventory_2_outlined,
        context.localized(ru: 'Товары', uk: 'Товари'),
      ),
      DashboardDestination(
        Icons.hub_outlined,
        context.localized(ru: 'Источники', uk: 'Джерела'),
      ),
    ];
    final content = IndexedStack(
      key: const ValueKey('dashboard-indexed-stack'),
      index: _selectedIndex,
      sizing: StackFit.expand,
      children: [
        if (_visitedTabs.contains(0))
          widget.initialRecommendationId != null || widget.legacyPricing
              ? RecommendationsPage(
                  onOpenCatalog: () => _select(_catalogIndex),
                  canAdministerWorkspace: canAdministerWorkspace,
                  initialRecommendationId: widget.initialRecommendationId,
                  onOpenRecommendationDeepLink: widget.routeNavigation
                      ? _openRecommendation
                      : null,
                )
              : AttentionPage(
                  onOpenSources: () => _select(_storesIndex),
                  onOpenRecommendation: _openRecommendation,
                )
        else
          const SizedBox.shrink(),
        if (_visitedTabs.contains(_catalogIndex))
          CatalogPage(
            onOpenPriceComparison: () => _select(0),
            canAdministerWorkspace: canAdministerWorkspace,
            initialStoreId: _catalogStoreId,
            onInitialStoreApplied: _clearCatalogStore,
            initialProductId: widget.initialCatalogProductId,
            onOpenProductDeepLink: widget.routeNavigation
                ? _openCatalogProduct
                : null,
          )
        else
          const SizedBox.shrink(),
        if (_visitedTabs.contains(_storesIndex))
          StoresPage(
            ownedOnly: true,
            canAdministerWorkspace: canAdministerWorkspace,
            onOpenStoreCatalog: _openStoreInCatalog,
            onImportCatalog: canAdministerWorkspace
                ? () => _showCatalogImport(canAdministerWorkspace)
                : null,
          )
        else
          const SizedBox.shrink(),
      ],
    );

    return MarkoWorkspaceChrome(
      destinations: destinations,
      selectedIndex: _selectedIndex,
      email: user?.email,
      language: language,
      onSelected: _select,
      onLanguageSelected: _selectLanguage,
      onLogout: _logout,
      child: content,
    );
  }

  void _select(int index) {
    if (index == _selectedIndex) return;
    setState(() {
      _visitedTabs.add(index);
      _selectedIndex = index;
    });
  }

  void _openCatalogProduct(String productId) {
    context.goNamed(
      'catalog-product',
      pathParameters: {'productId': productId},
    );
  }

  void _openRecommendation(String recommendationId) {
    context.goNamed(
      'pricing-recommendation',
      pathParameters: {'recommendationId': recommendationId},
    );
  }

  void _openStoreInCatalog(String storeId) {
    setState(() {
      _catalogStoreId = storeId;
      _visitedTabs.add(_catalogIndex);
      _selectedIndex = _catalogIndex;
    });
  }

  void _clearCatalogStore() {
    if (_catalogStoreId == null) return;
    setState(() => _catalogStoreId = null);
  }

  void _showCatalogImport(bool canAdministerWorkspace) {
    showCatalogImportDialog(
      context: context,
      canAdministerWorkspace: canAdministerWorkspace,
      onImported: () {
        ref.invalidate(catalogControllerProvider);
        ref.invalidate(attentionControllerProvider);
      },
    );
  }

  void _selectLanguage(AppLanguage language) =>
      ref.read(appLanguageProvider.notifier).select(language);

  void _logout() => ref.read(authControllerProvider.notifier).logout();
}

class MarkoWorkspaceChrome extends ConsumerWidget {
  const MarkoWorkspaceChrome({
    required this.destinations,
    required this.selectedIndex,
    required this.email,
    required this.language,
    required this.onSelected,
    required this.onLanguageSelected,
    required this.onLogout,
    required this.child,
    super.key,
  });

  final List<DashboardDestination> destinations;
  final int selectedIndex;
  final String? email;
  final AppLanguage language;
  final ValueChanged<int> onSelected;
  final ValueChanged<AppLanguage> onLanguageSelected;
  final VoidCallback onLogout;
  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      body: MarkoAtmosphere(
        beams: true,
        child: SafeArea(
          child: LayoutBuilder(
            builder: (context, constraints) {
              final wide = constraints.maxWidth >= MarkoBreakpoints.medium;
              if (wide) {
                return Row(
                  children: [
                    _Sidebar(
                      destinations: destinations,
                      selectedIndex: selectedIndex,
                      email: email,
                      language: language,
                      onSelected: onSelected,
                      onLanguageSelected: onLanguageSelected,
                      onLogout: onLogout,
                    ),
                    Expanded(
                      child: Column(
                        children: [
                          _PageBar(title: destinations[selectedIndex].label),
                          Expanded(child: child),
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
                    onLanguageSelected: onLanguageSelected,
                    onLogout: onLogout,
                  ),
                  Expanded(child: child),
                  _MobileNavigation(
                    destinations: destinations,
                    selectedIndex: selectedIndex,
                    onSelected: onSelected,
                  ),
                ],
              );
            },
          ),
        ),
      ),
    );
  }
}

class WorkspaceShell extends ConsumerWidget {
  const WorkspaceShell({required this.navigationShell, super.key});

  final StatefulNavigationShell navigationShell;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(authControllerProvider).value?.user;
    final language = ref.watch(appLanguageProvider);
    final destinations = <DashboardDestination>[
      DashboardDestination(
        Icons.notification_important_outlined,
        context.localized(ru: 'Требует внимания', uk: 'Потребує уваги'),
      ),
      DashboardDestination(
        Icons.inventory_2_outlined,
        context.localized(ru: 'Товары', uk: 'Товари'),
      ),
      DashboardDestination(
        Icons.hub_outlined,
        context.localized(ru: 'Источники', uk: 'Джерела'),
      ),
    ];
    return MarkoWorkspaceChrome(
      destinations: destinations,
      selectedIndex: navigationShell.currentIndex,
      email: user?.email,
      language: language,
      onSelected: (index) => navigationShell.goBranch(index),
      onLanguageSelected: (value) =>
          ref.read(appLanguageProvider.notifier).select(value),
      onLogout: () => ref.read(authControllerProvider.notifier).logout(),
      child: KeyedSubtree(
        key: const ValueKey('dashboard-indexed-stack'),
        child: navigationShell,
      ),
    );
  }
}

class DashboardDestination {
  const DashboardDestination(this.icon, this.label);

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

  final List<DashboardDestination> destinations;
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
                  child: Column(
                    children: [
                      _LanguageSelector(
                        language: language,
                        onSelected: onLanguageSelected,
                      ),
                      const SizedBox(height: MarkoSpacing.xs),
                      const _ThemeModeButton(),
                    ],
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
    final selectorLabel = context.localized(
      ru: 'Выбрать язык',
      uk: 'Обрати мову',
    );
    return Semantics(
      container: true,
      button: true,
      label: selectorLabel,
      child: MarkoMenuButton<AppLanguage>(
        key: const ValueKey('language-selector'),
        tooltip: selectorLabel,
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
      ),
    );
  }
}

class _ThemeModeButton extends ConsumerWidget {
  const _ThemeModeButton();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = ref.watch(appThemeModeProvider);
    final (icon, label) = switch (mode) {
      ThemeMode.light => (
        Icons.light_mode_outlined,
        context.localized(ru: 'Светлая тема', uk: 'Світла тема'),
      ),
      ThemeMode.dark => (
        Icons.dark_mode_outlined,
        context.localized(ru: 'Тёмная тема', uk: 'Темна тема'),
      ),
      ThemeMode.system => (
        Icons.contrast_rounded,
        context.localized(ru: 'Как в системе', uk: 'Як у системі'),
      ),
    };
    return OutlinedButton.icon(
      onPressed: () => ref.read(appThemeModeProvider.notifier).cycle(),
      icon: Icon(icon, size: 18),
      label: Text(label),
    );
  }
}

class _SidebarItem extends StatelessWidget {
  const _SidebarItem({
    required this.destination,
    required this.selected,
    required this.onTap,
  });

  final DashboardDestination destination;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 3),
      child: AnimatedContainer(
        duration: MarkoMotion.hover,
        curve: MarkoMotion.hoverCurve,
        decoration: BoxDecoration(
          color: selected ? colors.brandSoft : Colors.transparent,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Material(
          color: Colors.transparent,
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
                        fontWeight: selected
                            ? FontWeight.w600
                            : FontWeight.w500,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _PageBar extends ConsumerWidget {
  const _PageBar({required this.title});

  final String title;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = MarkoTheme.of(context);
    final status = ref.watch(systemStatusProvider);
    final (label, foreground, background) = status.when(
      loading: () => (
        context.localized(ru: 'Проверка системы', uk: 'Перевірка системи'),
        colors.muted,
        colors.surfaceMuted,
      ),
      error: (_, _) => (
        context.localized(ru: 'Система недоступна', uk: 'Система недоступна'),
        colors.negative,
        colors.negativeSoft,
      ),
      data: (health) => switch (health) {
        SystemHealth.active => (
          context.localized(ru: 'Система активна', uk: 'Система активна'),
          colors.positive,
          colors.positiveSoft,
        ),
        SystemHealth.collectionLimited => (
          context.localized(ru: 'Сбор ограничен', uk: 'Збір обмежено'),
          colors.warning,
          colors.warningSoft,
        ),
      },
    );
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
              color: background,
              borderRadius: BorderRadius.circular(7),
            ),
            child: Row(
              children: [
                MarkoStatusPulse(color: foreground),
                const SizedBox(width: 7),
                Text(
                  label,
                  style: Theme.of(
                    context,
                  ).textTheme.labelMedium?.copyWith(color: foreground),
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
          const Expanded(
            child: Align(
              alignment: Alignment.centerLeft,
              child: MarkoWordmark(compact: true),
            ),
          ),
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

  final List<DashboardDestination> destinations;
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
                    AnimatedContainer(
                      duration: MarkoMotion.hover,
                      curve: MarkoMotion.hoverCurve,
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 4,
                      ),
                      decoration: BoxDecoration(
                        color: selected ? colors.brandSoft : Colors.transparent,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Icon(
                        item.icon,
                        size: 20,
                        color: selected ? colors.brand : colors.muted,
                      ),
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
