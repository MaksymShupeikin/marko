import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:heroicons/heroicons.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/app_theme.dart';
import '../../../core/marko_ui.dart';
import '../../../core/widgets/marko_button.dart';
import '../products_controller.dart';
import '../products_models.dart';

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
          const SizedBox(height: MarkoSpace.md),
          Row(
            children: [
              HeroIcon(HeroIcons.clock, size: 14, color: colors.faint),
              const SizedBox(width: 5),
              Text(
                'Нещодавні пошуки',
                style: MarkoType.caption.copyWith(color: colors.faint),
              ),
              const Spacer(),
              InkWell(
                onTap: searchBusy
                    ? null
                    : () => ref.read(oemHistoryProvider.notifier).clear(),
                borderRadius: BorderRadius.circular(MarkoRadius.xs),
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 4,
                    vertical: 2,
                  ),
                  child: Text(
                    'Очистити',
                    style: MarkoType.caption.copyWith(
                      color: colors.faint,
                      fontSize: 11,
                    ),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: MarkoSpace.xs),
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
      error: (error, _) => MarkoInlineMessage(
        message: error.toString(),
        tone: MarkoMessageTone.error,
        action: TextButton(
          onPressed: () => ref.read(competitorSearchProvider.notifier).reset(),
          child: const Text('Закрити'),
        ),
      ),
      data: (result) => result == null
          ? const SizedBox.shrink()
          : _ResultsPanel(
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
          ClipRRect(
            borderRadius: BorderRadius.circular(MarkoRadius.xs),
            child: LinearProgressIndicator(
              minHeight: 3,
              color: colors.brand,
              backgroundColor: colors.surfaceMuted,
            ),
          ),
          const SizedBox(height: MarkoSpace.lg),
          AnimatedSwitcher(
            duration: const Duration(milliseconds: 250),
            child: Text(
              stage,
              key: ValueKey(stage),
              style: MarkoType.caption.copyWith(
                color: colors.ink,
                fontWeight: FontWeight.w500,
              ),
            ),
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

class _ResultsPanel extends StatefulWidget {
  const _ResultsPanel({required this.result, required this.onClose});

  final CompetitorPriceReport result;
  final VoidCallback onClose;

  @override
  State<_ResultsPanel> createState() => _ResultsPanelState();
}

class _ResultsPanelState extends State<_ResultsPanel> {
  static const _collapsedCount = 8;
  bool _expanded = false;

  @override
  void didUpdateWidget(covariant _ResultsPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.result != widget.result) _expanded = false;
  }

  @override
  Widget build(BuildContext context) {
    final result = widget.result;
    final stats = result.stats;
    final currency = result.currency;
    // Одна цінова драбина на всі джерела, від дешевшого.
    final offers = result.sources.expand((s) => s.offers).toList()
      ..sort((a, b) => a.price.compareTo(b.price));
    final visible = _expanded
        ? offers
        : offers.take(_collapsedCount).toList(growable: false);

    final colors = MarkoTheme.of(context);
    return MarkoPanel(
      padding: const EdgeInsets.all(MarkoSpace.xl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
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
                          'пропозицій: ${stats.offersTotal}',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              IconButton(
                tooltip: 'Сховати результати',
                onPressed: widget.onClose,
                icon: const HeroIcon(HeroIcons.xMark, size: 17),
              ),
            ],
          ),
          if (offers.isEmpty) ...[
            const SizedBox(height: MarkoSpace.md),
            const MarkoInlineMessage(
              message:
                  'Пропозицій із ціною не знайдено. Спробуйте інший номер або бренд.',
            ),
          ] else ...[
            const SizedBox(height: MarkoSpace.lg),
            PriceSpreadBar(
              min: stats.minPrice,
              median: stats.medianPrice,
              max: stats.maxPrice,
              currency: currency,
            ),
            const SizedBox(height: MarkoSpace.sm),
            for (var index = 0; index < visible.length; index++) ...[
              _OfferRow(offer: visible[index]),
              if (index < visible.length - 1) const Divider(),
            ],
            if (offers.length > _collapsedCount) ...[
              const SizedBox(height: 6),
              Center(
                child: TextButton(
                  onPressed: () => setState(() => _expanded = !_expanded),
                  child: Text(
                    _expanded ? 'Згорнути' : 'Показати всі ${offers.length}',
                  ),
                ),
              ),
            ],
          ],
        ],
      ),
    );
  }
}

/// Market spread as one spectrum: best price on the left, worst on the right,
/// median marked where it actually falls between them.
class PriceSpreadBar extends StatelessWidget {
  const PriceSpreadBar({
    required this.min,
    required this.median,
    required this.max,
    required this.currency,
    super.key,
  });

  final double? min;
  final double? median;
  final double? max;
  final String currency;

  String _money(double? value) =>
      value == null ? '—' : '${value.toStringAsFixed(0)} $currency';

  /// Where the median sits between min and max, 0..1. Centred when unknown.
  double get _medianFraction {
    final low = min;
    final high = max;
    final mid = median;
    if (low == null || high == null || mid == null || high <= low) return 0.5;
    return ((mid - low) / (high - low)).clamp(0.0, 1.0);
  }

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: MarkoSpace.lg,
        vertical: MarkoSpace.md,
      ),
      decoration: BoxDecoration(
        color: colors.surfaceMuted,
        borderRadius: BorderRadius.circular(MarkoRadius.md),
        border: Border.all(color: colors.border),
      ),
      child: Column(
        children: [
          Row(
            children: [
              Expanded(
                child: _Stat(
                  label: 'Мінімум',
                  value: _money(min),
                  tone: colors.positive,
                ),
              ),
              Expanded(
                child: _Stat(
                  label: 'Медіана',
                  value: _money(median),
                  tone: colors.ink,
                  align: CrossAxisAlignment.center,
                ),
              ),
              Expanded(
                child: _Stat(
                  label: 'Максимум',
                  value: _money(max),
                  tone: colors.negative,
                  align: CrossAxisAlignment.end,
                ),
              ),
            ],
          ),
          const SizedBox(height: MarkoSpace.md),
          LayoutBuilder(
            builder: (context, constraints) {
              const dot = 10.0;
              final offset = (constraints.maxWidth - dot) * _medianFraction;
              return SizedBox(
                height: dot,
                child: Stack(
                  children: [
                    Positioned.fill(
                      child: Center(
                        child: Container(
                          height: 5,
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(999),
                            gradient: LinearGradient(
                              colors: [colors.positive, colors.negative],
                            ),
                          ),
                        ),
                      ),
                    ),
                    Positioned(
                      left: offset,
                      child: Container(
                        width: dot,
                        height: dot,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: colors.ink,
                          border: Border.all(color: colors.surface, width: 2),
                          boxShadow: [
                            BoxShadow(
                              color: Colors.black.withValues(alpha: 0.3),
                              blurRadius: 3,
                              offset: const Offset(0, 1),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              );
            },
          ),
        ],
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat({
    required this.label,
    required this.value,
    required this.tone,
    this.align = CrossAxisAlignment.start,
  });

  final String label;
  final String value;
  final Color tone;
  final CrossAxisAlignment align;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Column(
      crossAxisAlignment: align,
      children: [
        Text(
          label,
          style: MarkoType.caption.copyWith(
            color: colors.muted,
            fontSize: 11,
            fontWeight: FontWeight.w500,
          ),
        ),
        const SizedBox(height: MarkoSpace.xs),
        Text(
          value,
          style: MarkoType.price.copyWith(
            color: tone,
            fontWeight: FontWeight.w700,
          ),
        ),
      ],
    );
  }
}

class _OfferRow extends StatelessWidget {
  const _OfferRow({required this.offer});

  final MarketPriceOffer offer;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return InkWell(
      onTap: offer.url.isEmpty
          ? null
          : () => launchUrl(
              Uri.parse(offer.url),
              mode: LaunchMode.externalApplication,
            ),
      borderRadius: BorderRadius.circular(MarkoRadius.sm),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: MarkoSpace.md),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    offer.title,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: colors.ink,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                  if (offer.subtitle.isNotEmpty) ...[
                    const SizedBox(height: MarkoSpace.xxs),
                    Text(
                      offer.subtitle,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(
                        context,
                      ).textTheme.bodySmall?.copyWith(color: colors.muted),
                    ),
                  ],
                ],
              ),
            ),
            if (offer.isAnalog) ...[
              MarkoStatusPill(label: 'аналог', tone: colors.warning),
              const SizedBox(width: MarkoSpace.sm),
            ],
            Text(
              offer.priceLabel,
              style: MarkoType.price.copyWith(
                color: colors.ink,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
