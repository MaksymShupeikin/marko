import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:heroicons/heroicons.dart';

import '../../core/app_theme.dart';
import '../../core/marko_ui.dart';
import '../../core/widgets/marko_button.dart';
import '../auth/auth_controller.dart';
import '../auth/auth_models.dart';
import '../auth/widgets/sign_out_dialog.dart';
import '../products/products_controller.dart';
import '../products/products_page.dart';
import '../products/widgets/competitor_results.dart';
import '../products/widgets/help_overlay.dart';
import '../products/widgets/source_panel.dart';

/// One screen: the app is the product catalog, everything else hangs off it.
class DashboardPage extends ConsumerWidget {
  const DashboardPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = MarkoTheme.of(context);
    final width = MediaQuery.sizeOf(context).width;
    final compact = width < MarkoLayout.compactWidth;
    // The onboarding screen carries its own import cards.
    final emptyCatalog =
        ref.watch(productsControllerProvider).value?.isPristineEmpty ?? false;

    return Scaffold(
      // Статус-бар зафарбовує сам топбар, а низ віддано скролу — тому лише боки.
      body: SafeArea(
        top: false,
        bottom: false,
        child: Stack(
          children: [
            const Column(
              children: [
                _TopBar(),
                Expanded(child: ProductsPage()),
              ],
            ),
            if (compact && !emptyCatalog)
              Positioned(
                left: 0,
                right: 0,
                bottom: 0,
                child: Container(
                  decoration: BoxDecoration(
                    color: colors.surface.withValues(alpha: 0.96),
                    border: Border(top: BorderSide(color: colors.border)),
                    boxShadow: MarkoShadow.overlay,
                  ),
                  child: MarkoContentFrame(
                    child: Padding(
                      padding: EdgeInsets.fromLTRB(
                        0,
                        MarkoSpace.sm,
                        0,
                        MarkoSpace.sm + MediaQuery.paddingOf(context).bottom,
                      ),
                      child: Row(
                        children: [
                          Expanded(
                            child: MarkoButton.secondary(
                              label: 'Імпорт',
                              icon: HeroIcons.arrowDownTray,
                              onPressed: () => showCatalogImport(context),
                            ),
                          ),
                          const SizedBox(width: MarkoSpace.sm),
                          Expanded(
                            child: MarkoButton(
                              label: 'Конкуренти',
                              icon: HeroIcons.magnifyingGlass,
                              onPressed: () => showOemLookup(context),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// The top bar carries navigation, theme toggle, catalog import (secondary),
/// and fast OEM price lookup (primary, to the right of import) with adaptive layouts.
class _TopBar extends ConsumerWidget {
  const _TopBar();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = MarkoTheme.of(context);
    final user = ref.watch(authControllerProvider).value?.user;
    final emptyCatalog =
        ref.watch(productsControllerProvider).value?.isPristineEmpty ?? false;

    return Container(
      // Смуга статус-бара — це продовження топбара, а не сірий полотняний фон.
      padding: EdgeInsets.only(top: MediaQuery.paddingOf(context).top),
      decoration: BoxDecoration(
        color: colors.surface,
        border: Border(bottom: BorderSide(color: colors.border)),
      ),
      child: MarkoContentFrame(
        child: LayoutBuilder(
          builder: (context, constraints) {
            final compact = constraints.maxWidth < MarkoLayout.compactWidth;

            final bar = Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                const MarkoWordmark(compact: true),
                const SizedBox(width: MarkoSpace.sm),
                _Divider(color: colors.border),
                const SizedBox(width: MarkoSpace.xs),
                TextButton.icon(
                  onPressed: () => showHelpOverlay(context),
                  icon: HeroIcon(
                    HeroIcons.bookOpen,
                    size: 16,
                    color: colors.muted,
                  ),
                  label: const Text('Інструкція'),
                  style: TextButton.styleFrom(
                    foregroundColor: colors.muted,
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    textStyle: Theme.of(
                      context,
                    ).textTheme.labelMedium?.copyWith(fontSize: 13),
                  ),
                ),
                const Spacer(),
                if (compact) ...[
                  const MarkoThemeToggle(),
                  // Дотикові кнопки й так по 38px — між ними вистачає волосини.
                  const SizedBox(width: MarkoSpace.xxs),
                  if (user != null)
                    IconButton(
                      tooltip: 'Вийти з акаунта',
                      onPressed: () async {
                        final confirmed = await confirmSignOut(context, user: user);
                        if (confirmed) {
                          await ref.read(authControllerProvider.notifier).logout();
                        }
                      },
                      icon: HeroIcon(
                        HeroIcons.arrowRightStartOnRectangle,
                        size: 19,
                        color: colors.muted,
                      ),
                    ),
                ] else ...[
                  if (!emptyCatalog) ...[
                    // Secondary Action: Catalog Ingestion Toggle
                    MarkoButton.secondary(
                      label: 'Імпорт каталогу',
                      icon: HeroIcons.arrowDownTray,
                      onPressed: () => showCatalogImport(context),
                    ),
                    const SizedBox(width: MarkoSpace.sm),
                    // Primary Action: Competitor Prices Lookup (to the right of Import)
                    MarkoButton(
                      label: 'Ціни конкурентів',
                      icon: HeroIcons.magnifyingGlass,
                      onPressed: () => showOemLookup(context),
                    ),
                    const SizedBox(width: MarkoSpace.md),
                    _Divider(color: colors.border),
                    const SizedBox(width: MarkoSpace.sm),
                  ],
                  const MarkoThemeToggle(),
                  const SizedBox(width: MarkoSpace.xs),
                  if (user != null)
                    _AccountButton(
                      user: user,
                      showName: true,
                      onLogout: () async {
                        final confirmed = await confirmSignOut(context, user: user);
                        if (confirmed) {
                          await ref.read(authControllerProvider.notifier).logout();
                        }
                      },
                    ),
                ],
              ],
            );

            return SizedBox(height: MarkoLayout.appBarHeight, child: bar);
          },
        ),
      ),
    );
  }
}

/// Who is signed in and the way out, in one control.
class _AccountButton extends StatefulWidget {
  const _AccountButton({
    required this.user,
    required this.showName,
    required this.onLogout,
  });

  final AuthUser user;
  final bool showName;
  final VoidCallback onLogout;

  @override
  State<_AccountButton> createState() => _AccountButtonState();
}

class _AccountButtonState extends State<_AccountButton> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final user = widget.user;
    return Tooltip(
      message: 'Вийти з ${user.email}',
      child: MouseRegion(
        cursor: SystemMouseCursors.click,
        onEnter: (_) => setState(() => _hovered = true),
        onExit: (_) => setState(() => _hovered = false),
        child: Semantics(
          button: true,
          label: 'Вийти з акаунта ${user.shortName}',
          excludeSemantics: true,
          child: GestureDetector(
            onTap: widget.onLogout,
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 150),
              curve: Curves.easeInOut,
              height: MarkoLayout.fieldHeightOf(context),
              padding: const EdgeInsets.symmetric(horizontal: 5),
              decoration: BoxDecoration(
                color: _hovered ? colors.surfaceMuted : Colors.transparent,
                borderRadius: BorderRadius.circular(MarkoRadius.md),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const _Avatar(),
                  if (widget.showName) ...[
                    const SizedBox(width: MarkoSpace.sm),
                    ConstrainedBox(
                      constraints: const BoxConstraints(maxWidth: 160),
                      child: Text(
                        user.shortName,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.labelLarge,
                      ),
                    ),
                  ],
                  AnimatedSize(
                    duration: const Duration(milliseconds: 150),
                    curve: Curves.easeInOut,
                    alignment: Alignment.centerLeft,
                    child: _hovered
                        ? Padding(
                            padding: const EdgeInsets.only(
                              left: MarkoSpace.sm,
                              right: MarkoSpace.xxs,
                            ),
                            child: HeroIcon(
                              HeroIcons.arrowRightStartOnRectangle,
                              size: 16,
                              color: colors.ink,
                            ),
                          )
                        : const SizedBox(height: 16),
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

/// Plain user glyph — no photo fetch, no initial.
class _Avatar extends StatelessWidget {
  const _Avatar();

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      width: 26,
      height: 26,
      decoration: BoxDecoration(
        color: colors.brandSoft,
        shape: BoxShape.circle,
        border: Border.all(color: colors.brand.withValues(alpha: 0.24)),
      ),
      alignment: Alignment.center,
      child: HeroIcon(HeroIcons.user, size: 14, color: colors.brand),
    );
  }
}

class _Divider extends StatelessWidget {
  const _Divider({required this.color});

  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(width: 1, height: 22, color: color);
  }
}
