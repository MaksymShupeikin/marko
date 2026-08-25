import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:heroicons/heroicons.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../../core/app_theme.dart';
import '../../../core/marko_ui.dart';
import '../../billing/paywall.dart';
import '../../../core/widgets/marko_button.dart';
import '../../../core/widgets/marko_loader.dart';
import '../products_controller.dart';
import '../products_models.dart';
import 'product_details_panel.dart';

class OemHistoryItem {
  const OemHistoryItem({required this.oem, required this.brand});

  final String oem;
  final String brand;

  Map<String, String> toJson() => {'oem': oem, 'brand': brand};

  factory OemHistoryItem.fromJson(Map<String, dynamic> json) =>
      OemHistoryItem(oem: json['oem'] ?? '', brand: json['brand'] ?? '');
}

const _oemHistoryKey = 'marko_oem_search_history';

class OemHistoryController extends Notifier<List<OemHistoryItem>> {
  @override
  List<OemHistoryItem> build() {
    _load();
    return const [];
  }

  Future<void> _load() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final list = prefs.getStringList(_oemHistoryKey);
      if (list != null) {
        state = list
            .map(
              (s) => OemHistoryItem.fromJson(
                jsonDecode(s) as Map<String, dynamic>,
              ),
            )
            .where((item) => item.oem.isNotEmpty)
            .toList();
      }
    } catch (_) {}
  }

  Future<void> add(String oem, String brand) async {
    final cleanOem = oem.trim();
    final cleanBrand = brand.trim();
    if (cleanOem.isEmpty) return;

    final updated = [
      OemHistoryItem(oem: cleanOem, brand: cleanBrand),
      ...state.where((i) => i.oem.toUpperCase() != cleanOem.toUpperCase()),
    ].take(6).toList();

    state = updated;

    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setStringList(
        _oemHistoryKey,
        updated.map((i) => jsonEncode(i.toJson())).toList(),
      );
    } catch (_) {}
  }

  Future<void> clear() async {
    state = const [];
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove(_oemHistoryKey);
    } catch (_) {}
  }
}

final oemHistoryProvider =
    NotifierProvider<OemHistoryController, List<OemHistoryItem>>(
      OemHistoryController.new,
    );

/// Real-time competitor price lookup over the catalog.
Future<void> showOemLookup(BuildContext context) => showMarkoModal(
  context,
  icon: HeroIcons.magnifyingGlass,
  title: 'Ціни конкурентів',
  subtitle: 'Миттєвий пошук ринкових цін за OEM',
  child: const _OemLookupContent(),
);

class _OemLookupContent extends ConsumerStatefulWidget {
  const _OemLookupContent();

  @override
  ConsumerState<_OemLookupContent> createState() => _OemLookupContentState();
}

class _OemLookupContentState extends ConsumerState<_OemLookupContent> {
  static const _samples = [
    ('701807101', 'VOLKSWAGEN'),
    ('1K0129620D', 'VOLKSWAGEN'),
    ('93818439', 'IVECO'),
  ];

  final _oemController = TextEditingController();
  final _brandController = TextEditingController();

  @override
  void dispose() {
    _oemController.dispose();
    _brandController.dispose();
    super.dispose();
  }

  void _quickPick(String oem, String brand) {
    _oemController.text = oem;
    _brandController.text = brand;
    _lookup();
  }

  void _lookup() {
    final oem = _oemController.text.trim();
    final brand = _brandController.text.trim();
    if (oem.isEmpty) return;

    FocusManager.instance.primaryFocus?.unfocus();
    ref.read(oemHistoryProvider.notifier).add(oem, brand);
    ref.read(competitorSearchProvider.notifier).search(oem, brand: brand);
  }

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final searchBusy = ref.watch(competitorSearchProvider).isLoading;
    final history = ref.watch(oemHistoryProvider);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Expanded(
              flex: 3,
              child: MarkoTextField(
                controller: _oemController,
                enabled: !searchBusy,
                style: MarkoType.oem.copyWith(color: colors.ink, fontSize: 14),
                labelText: 'OEM номер або назва',
                hintText: '701807101',
                prefixIcon: HeroIcons.hashtag,
                onSubmitted: (_) => searchBusy ? null : _lookup(),
              ),
            ),
            const SizedBox(width: MarkoSpace.md),
            Expanded(
              flex: 2,
              child: MarkoTextField(
                controller: _brandController,
                enabled: !searchBusy,
                labelText: 'Бренд',
                hintText: 'VOLKSWAGEN',
                prefixIcon: HeroIcons.tag,
                onSubmitted: (_) => searchBusy ? null : _lookup(),
              ),
            ),
          ],
        ),
        const SizedBox(height: MarkoSpace.md),
        MarkoButton(
          label: 'Знайти ціни',
          onPressed: searchBusy ? null : _lookup,
          icon: HeroIcons.magnifyingGlass,
          loading: searchBusy,
          expand: true,
        ),
        if (history.isNotEmpty) ...[
          const SizedBox(height: MarkoSpace.lg),
          Text(
            'Останні пошуки',
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: MarkoSpace.sm),
          Wrap(
            spacing: MarkoSpace.sm,
            runSpacing: MarkoSpace.sm,
            children: [
              for (final item in history)
                _SampleChip(
                  oem: item.oem,
                  brand: item.brand,
                  isHistory: true,
                  onTap: searchBusy
                      ? null
                      : () => _quickPick(item.oem, item.brand),
                ),
            ],
          ),
        ],
        const SizedBox(height: MarkoSpace.md),
        Wrap(
          spacing: MarkoSpace.sm,
          runSpacing: MarkoSpace.sm,
          children: [
            for (final (oem, brand) in _samples)
              if (!history.any((h) => h.oem.toUpperCase() == oem.toUpperCase()))
                _SampleChip(
                  oem: oem,
                  brand: brand,
                  onTap: searchBusy ? null : () => _quickPick(oem, brand),
                ),
          ],
        ),
        const SizedBox(height: MarkoSpace.xl),
        const CompetitorResults(),
      ],
    );
  }
}

class _SampleChip extends StatefulWidget {
  const _SampleChip({
    required this.oem,
    required this.brand,
    required this.onTap,
    this.isHistory = false,
  });

  final String oem;
  final String brand;
  final VoidCallback? onTap;
  final bool isHistory;

  @override
  State<_SampleChip> createState() => _SampleChipState();
}

class _SampleChipState extends State<_SampleChip> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final isClickable = widget.onTap != null;

    return MouseRegion(
      cursor: isClickable ? SystemMouseCursors.click : MouseCursor.defer,
      onEnter: (_) => setState(() => _hovered = true),
      onExit: (_) => setState(() => _hovered = false),
      child: GestureDetector(
        onTap: widget.onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 160),
          curve: Curves.easeOutCubic,
          transform: Matrix4.translationValues(0, _hovered ? -1.5 : 0, 0),
          padding: const EdgeInsets.symmetric(
            horizontal: MarkoSpace.sm,
            vertical: 5,
          ),
          decoration: BoxDecoration(
            color: _hovered ? colors.surface : colors.surfaceMuted,
            borderRadius: BorderRadius.circular(MarkoRadius.sm),
            border: Border.all(
              color: _hovered
                  ? colors.brand.withValues(alpha: 0.65)
                  : colors.border,
              width: _hovered ? 1.2 : 1.0,
            ),
            boxShadow: _hovered
                ? [
                    BoxShadow(
                      color: colors.brand.withValues(alpha: 0.12),
                      blurRadius: 8,
                      offset: const Offset(0, 2),
                    ),
                  ]
                : null,
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (widget.isHistory) ...[
                HeroIcon(
                  HeroIcons.clock,
                  size: 12,
                  color: _hovered ? colors.brand : colors.faint,
                ),
                const SizedBox(width: 4),
              ],
              Text(
                widget.oem,
                style: MarkoType.oem.copyWith(
                  color: _hovered ? colors.brand : colors.ink,
                  fontWeight: _hovered ? FontWeight.w600 : FontWeight.w500,
                ),
              ),
              const SizedBox(width: 6),
              Text(
                widget.brand,
                style: MarkoType.caption.copyWith(
                  color: _hovered ? colors.muted : colors.faint,
                ),
              ),
              if (_hovered) ...[
                const SizedBox(width: 4),
                HeroIcon(HeroIcons.arrowUpRight, size: 12, color: colors.brand),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

/// Results of the one-off avto.pro lookup. Renders nothing until searched.
class CompetitorResults extends ConsumerWidget {
  const CompetitorResults({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(competitorSearchProvider);
    return async.when(
      loading: () => const _ResultsSkeleton(),
      error: (error, _) => isPaywallError(error)
          ? const Center(child: PaywallCard())
          : MarkoInlineMessage(
              message: error.toString(),
              tone: MarkoMessageTone.error,
              action: TextButton(
                onPressed: () =>
                    ref.read(competitorSearchProvider.notifier).reset(),
                child: const Text('Закрити'),
              ),
            ),
      data: (result) => result == null
          ? (showPaywallDemo
              ? const Center(child: PaywallCard())
              : const SizedBox.shrink())
          : CompetitorResultsPanel(
              result: result,
              onClose: () =>
                  ref.read(competitorSearchProvider.notifier).reset(),
            ),
    );
  }
}

class _ResultsSkeleton extends ConsumerWidget {
  const _ResultsSkeleton();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = MarkoTheme.of(context);
    final stage =
        ref.watch(competitorStageProvider(manualSearchKey)) ??
        'Скануємо актуальні ціни на ринку...';
    Widget bar(double width) => Container(
      height: 12,
      width: width,
      decoration: BoxDecoration(
        color: colors.surfaceMuted,
        borderRadius: BorderRadius.circular(MarkoRadius.sm),
      ),
    );
    return MarkoPanel(
      padding: const EdgeInsets.all(MarkoSpace.xl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const MarkoLoader(size: 14),
              const SizedBox(width: MarkoSpace.sm),
              Expanded(
                child: AnimatedSwitcher(
                  duration: const Duration(milliseconds: 250),
                  layoutBuilder: (currentChild, previousChildren) => Stack(
                    alignment: Alignment.centerLeft,
                    children: <Widget>[
                      ...previousChildren,
                      ?currentChild,
                    ],
                  ),
                  child: SizedBox(
                    key: ValueKey(stage),
                    width: double.infinity,
                    child: Text(
                      stage,
                      textAlign: TextAlign.left,
                      style: MarkoType.caption.copyWith(
                        color: colors.ink,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: MarkoSpace.lg),
          for (final width in const [400.0, 320.0, 260.0]) ...[
            bar(width),
            const SizedBox(height: MarkoSpace.md),
          ],
        ],
      ),
    );
  }
}

/// The market report panel: same widgets as on the product details sheet
/// (benchmark gauge + offer cards), just without an own price to compare to.
class CompetitorResultsPanel extends StatelessWidget {
  const CompetitorResultsPanel({required this.result, this.onClose, super.key});

  final CompetitorPriceReport result;
  final VoidCallback? onClose;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return MarkoPanel(
      padding: const EdgeInsets.all(MarkoSpace.xl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Знайдено на ринку',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: MarkoSpace.sm),
                    Wrap(
                      spacing: MarkoSpace.sm,
                      runSpacing: MarkoSpace.xs,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        for (final source in result.sources)
                          MarkoStatusPill(
                            label:
                                '${source.label}: ${source.offers.length}',
                            tone: source.hasOffers
                                ? colors.positive
                                : colors.muted,
                          ),
                        Text(
                          'пропозицій: ${result.stats.offersTotal}',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              if (onClose != null)
                IconButton(
                  tooltip: 'Сховати результати',
                  onPressed: onClose,
                  icon: const HeroIcon(HeroIcons.xMark, size: 17),
                ),
            ],
          ),
          const SizedBox(height: MarkoSpace.md),
          CompetitorPricesReport(report: result),
        ],
      ),
    );
  }
}
