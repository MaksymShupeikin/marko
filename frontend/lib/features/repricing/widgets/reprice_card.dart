import 'package:flutter/material.dart';
import 'package:heroicons/heroicons.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/app_theme.dart';
import '../../../core/marko_ui.dart';
import '../../../core/widgets/marko_cached_image.dart';
import '../repricing_models.dart';

/// One product's outcome, as a card rather than a table row.
///
/// Три результати мають різний вигляд навмисно: «без змін» і «не пораховано» —
/// протилежні твердження, і зливати їх в один нейтральний рядок означало б
/// сказати людині, що ми перевірили те, чого не перевіряли.
class RepriceCard extends StatelessWidget {
  const RepriceCard({
    required this.item,
    required this.onDismiss,
    required this.onOpenInCatalog,
    super.key,
  });

  final RepriceItem item;
  final VoidCallback onDismiss;
  final VoidCallback onOpenInCatalog;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      padding: const EdgeInsets.all(MarkoSpace.lg),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(MarkoRadius.lg),
        border: Border.all(color: colors.border),
      ),
      child: Opacity(
        opacity: item.dismissed ? 0.5 : 1,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                ClipRRect(
                  borderRadius: BorderRadius.circular(MarkoRadius.sm),
                  child: SizedBox(
                    width: 48,
                    height: 48,
                    child: MarkoCachedImage(imageUrl: item.imageUrl),
                  ),
                ),
                const SizedBox(width: MarkoSpace.md),
                Expanded(child: _Identity(item: item)),
                _DismissMenu(item: item, onDismiss: onDismiss),
              ],
            ),
            const SizedBox(height: MarkoSpace.md),
            _Verdict(item: item),
            if (item.priceChangedSince) ...[
              const SizedBox(height: MarkoSpace.sm),
              Text(
                'Ціна товару змінилась після розрахунку — варто перерахувати',
                style: MarkoType.caption.copyWith(color: colors.warning),
              ),
            ],
            const SizedBox(height: MarkoSpace.md),
            _Links(item: item, onOpenInCatalog: onOpenInCatalog),
          ],
        ),
      ),
    );
  }
}

class _Identity extends StatelessWidget {
  const _Identity({required this.item});

  final RepriceItem item;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final subtitle = [
      if (item.brand != null && item.brand!.isNotEmpty) item.brand!,
      if (item.storeName != null && item.storeName!.isNotEmpty) item.storeName!,
    ].join(' · ');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          item.name,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: Theme.of(
            context,
          ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 4),
        Row(
          children: [
            if (item.sku != null && item.sku!.isNotEmpty) ...[
              MarkoOemChip(item.sku!),
              const SizedBox(width: MarkoSpace.sm),
            ],
            Expanded(
              child: Text(
                subtitle,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: MarkoType.caption.copyWith(color: colors.muted),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _Verdict extends StatelessWidget {
  const _Verdict({required this.item});

  final RepriceItem item;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return switch (item.outcome) {
      RepriceOutcome.changed => _ChangedVerdict(item: item),
      RepriceOutcome.unchanged => Row(
        children: [
          HeroIcon(HeroIcons.checkCircle, size: 16, color: colors.positive),
          const SizedBox(width: MarkoSpace.sm),
          Expanded(
            child: Text(
              'Без змін — ціна вже відповідає ринку',
              style: MarkoType.caption.copyWith(color: colors.ink),
            ),
          ),
        ],
      ),
      _ => Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          HeroIcon(
            HeroIcons.exclamationTriangle,
            size: 16,
            color: colors.warning,
          ),
          const SizedBox(width: MarkoSpace.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Не пораховано',
                  style: Theme.of(
                    context,
                  ).textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 2),
                Text(
                  // Причина обов'язкова: «не пораховано» без неї нічого
                  // не пояснює, а виглядає як збій.
                  item.reason ?? 'Причина невідома',
                  style: MarkoType.caption.copyWith(color: colors.muted),
                ),
              ],
            ),
          ),
        ],
      ),
    };
  }
}

class _ChangedVerdict extends StatelessWidget {
  const _ChangedVerdict({required this.item});

  final RepriceItem item;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final percent = item.deltaPercent ?? 0;
    final falling = percent < 0;
    final currency = formatCurrency(item.currency);
    final tone = falling ? colors.brand : colors.positive;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.baseline,
          textBaseline: TextBaseline.alphabetic,
          children: [
            Text(
              '${formatPriceNumber(item.oldPrice ?? 0)} $currency',
              style: MarkoType.price.copyWith(
                color: colors.muted,
                decoration: TextDecoration.lineThrough,
              ),
            ),
            const SizedBox(width: MarkoSpace.sm),
            HeroIcon(HeroIcons.arrowRight, size: 14, color: colors.muted),
            const SizedBox(width: MarkoSpace.sm),
            Text(
              '${formatPriceNumber(item.newPrice ?? 0)} $currency',
              style: MarkoType.price.copyWith(
                color: tone,
                fontSize: 16,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(width: MarkoSpace.sm),
            Text(
              '${falling ? '↓' : '↑'} ${percent.abs().toStringAsFixed(1)}%',
              style: MarkoType.caption.copyWith(
                color: tone,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
        const SizedBox(height: MarkoSpace.sm),
        Wrap(
          spacing: MarkoSpace.sm,
          runSpacing: MarkoSpace.xs,
          children: [
            if (item.zoneLabel.isNotEmpty)
              MarkoStatusPill(label: item.zoneLabel, tone: colors.muted),
            if (item.tier != null && item.tier!.isNotEmpty)
              MarkoStatusPill(label: item.tier!, tone: colors.muted),
            MarkoStatusPill(
              label: '${item.offersTotal} пропозицій',
              tone: colors.muted,
            ),
          ],
        ),
      ],
    );
  }
}

class _Links extends StatelessWidget {
  const _Links({required this.item, required this.onOpenInCatalog});

  final RepriceItem item;
  final VoidCallback onOpenInCatalog;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Wrap(
      spacing: MarkoSpace.md,
      children: [
        TextButton.icon(
          onPressed: onOpenInCatalog,
          icon: HeroIcon(HeroIcons.squares2x2, size: 14, color: colors.brand),
          label: Text(
            'У каталозі',
            style: TextStyle(color: colors.brand, fontSize: 12.5),
          ),
        ),
        if (item.url.isNotEmpty)
          TextButton.icon(
            onPressed: () => launchUrl(
              Uri.parse(item.url),
              mode: LaunchMode.externalApplication,
            ),
            icon: HeroIcon(
              HeroIcons.arrowTopRightOnSquare,
              size: 14,
              color: colors.brand,
            ),
            label: Text(
              'На майданчику',
              style: TextStyle(color: colors.brand, fontSize: 12.5),
            ),
          ),
      ],
    );
  }
}

class _DismissMenu extends StatelessWidget {
  const _DismissMenu({required this.item, required this.onDismiss});

  final RepriceItem item;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return IconButton(
      tooltip: item.dismissed ? 'Повернути у звіт' : 'Сховати зі звіту',
      onPressed: onDismiss,
      icon: HeroIcon(
        item.dismissed ? HeroIcons.arrowUturnLeft : HeroIcons.eyeSlash,
        size: 16,
        color: colors.muted,
      ),
    );
  }
}
