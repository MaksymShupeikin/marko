import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/app_language.dart';
import '../../../core/app_theme.dart';
import '../../../core/marko_ui.dart';
import '../../../core/widgets/marko_cached_image.dart';
import '../store_models.dart';

/// A product the query found in another store, offered as a place to continue.
class CrossStoreMatchCard extends StatelessWidget {
  const CrossStoreMatchCard({
    required this.match,
    required this.onOpenStore,
    super.key,
  });

  final CrossStoreMatch match;

  /// Opens the connected store's catalog on this product. Absent for offers
  /// that only exist as an external marketplace observation.
  final void Function(CrossStoreMatch match)? onOpenStore;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final canOpenStore = match.isConnectedStore && onOpenStore != null;
    return MarkoPanel(
      padding: const EdgeInsets.all(12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(9),
            child: SizedBox.square(
              dimension: 56,
              child: ColoredBox(
                color: colors.surfaceMuted,
                child: MarkoCachedImage(
                  imageUrl: match.imageUrl,
                  fit: BoxFit.cover,
                ),
              ),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Flexible(
                      child: Text(
                        match.storeName,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.labelMedium
                            ?.copyWith(
                              color: colors.muted,
                              fontWeight: FontWeight.w600,
                            ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    _MatchBadge(match: match),
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  match.name,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                const SizedBox(height: 6),
                Row(
                  children: [
                    if (match.price != null) ...[
                      Text(
                        match.priceLabel,
                        style: Theme.of(context).textTheme.titleSmall,
                      ),
                      const SizedBox(width: 10),
                    ],
                    Flexible(
                      child: Text(
                        _matchExplanation(context),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(
                          context,
                        ).textTheme.bodySmall?.copyWith(color: colors.muted),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(width: 10),
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (canOpenStore)
                TextButton.icon(
                  onPressed: () => onOpenStore!(match),
                  icon: const Icon(Icons.arrow_forward_rounded, size: 16),
                  iconAlignment: IconAlignment.end,
                  label: Text(context.localized(ru: 'Перейти', uk: 'Перейти')),
                ),
              IconButton(
                tooltip: context.localized(
                  ru: 'Открыть на prom.ua',
                  uk: 'Відкрити на prom.ua',
                ),
                onPressed: () => _openExternally(match.url),
                icon: const Icon(Icons.open_in_new_rounded, size: 17),
              ),
            ],
          ),
        ],
      ),
    );
  }

  String _matchExplanation(BuildContext context) {
    final value = match.matchedValue;
    final lane = switch (match.matchedOn) {
      'oem' => context.localized(ru: 'по OEM $value', uk: 'за OEM $value'),
      'sku' => context.localized(ru: 'по SKU $value', uk: 'за SKU $value'),
      _ => context.localized(ru: 'по названию', uk: 'за назвою'),
    };
    if (!match.viaCross) return lane;
    return context.localized(
      ru: '$lane · подтверждённый кросс',
      uk: '$lane · підтверджений крос',
    );
  }

  Future<void> _openExternally(String url) async {
    final uri = Uri.tryParse(url);
    if (uri == null || !uri.hasScheme) return;
    await launchUrl(uri, mode: LaunchMode.externalApplication);
  }
}

class _MatchBadge extends StatelessWidget {
  const _MatchBadge({required this.match});

  final CrossStoreMatch match;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final (label, foreground, background) = switch (match.matchedOn) {
      'oem' => ('OEM', colors.brand, colors.brandSoft),
      'sku' => ('SKU', colors.positive, colors.positiveSoft),
      _ => (
        context.localized(ru: 'НАЗВАНИЕ', uk: 'НАЗВА'),
        colors.muted,
        colors.surfaceMuted,
      ),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        label,
        style: Theme.of(context).textTheme.labelSmall?.copyWith(
          color: foreground,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.4,
          fontSize: 10,
        ),
      ),
    );
  }
}
