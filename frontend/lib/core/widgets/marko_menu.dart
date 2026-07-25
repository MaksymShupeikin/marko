import 'package:flutter/material.dart';

import '../app_theme.dart';

/// One row inside a [MarkoMenuButton] popup.
class MarkoMenuEntry<T> {
  const MarkoMenuEntry({
    required this.value,
    required this.label,
    this.trailingLabel,
    this.icon,
    this.avatarText,
    this.dividerBefore = false,
  });

  final T value;
  final String label;

  /// Small muted text pinned to the right (language code, counters, ...).
  final String? trailingLabel;

  /// Leading glyph. Takes precedence over [avatarText].
  final IconData? icon;

  /// Leading monogram used when [icon] is not provided.
  final String? avatarText;

  final bool dividerBefore;
}

/// Popup menu styled to match the Marko surfaces: rounded card, hairline
/// border, soft shadow and a highlighted pill for the active row.
class MarkoMenuButton<T> extends StatelessWidget {
  const MarkoMenuButton({
    required this.entries,
    required this.selected,
    required this.onSelected,
    required this.child,
    this.tooltip,
    this.header,
    this.enabled = true,
    this.minWidth = 232,
    this.maxWidth = 320,
    this.offset = const Offset(0, 8),
    super.key,
  });

  final List<MarkoMenuEntry<T>> entries;
  final T? selected;
  final ValueChanged<T> onSelected;
  final Widget child;
  final String? tooltip;

  /// Optional uppercase caption rendered above the rows.
  final String? header;
  final bool enabled;
  final double minWidth;
  final double maxWidth;
  final Offset offset;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return PopupMenuButton<T>(
      tooltip: tooltip,
      enabled: enabled && entries.isNotEmpty,
      initialValue: selected,
      onSelected: onSelected,
      offset: offset,
      position: PopupMenuPosition.under,
      elevation: 0,
      color: colors.surface,
      surfaceTintColor: Colors.transparent,
      shadowColor: Colors.transparent,
      menuPadding: EdgeInsets.zero,
      popUpAnimationStyle: const AnimationStyle(
        duration: Duration(milliseconds: 140),
        curve: Curves.easeOutCubic,
      ),
      constraints: BoxConstraints(minWidth: minWidth, maxWidth: maxWidth),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.all(Radius.circular(14)),
      ),
      itemBuilder: (context) => [
        PopupMenuItem<T>(
          enabled: false,
          padding: EdgeInsets.zero,
          height: 0,
          child: _MarkoMenuSurface<T>(
            entries: entries,
            selected: selected,
            header: header,
            onSelected: (value) {
              Navigator.of(context).pop();
              onSelected(value);
            },
          ),
        ),
      ],
      child: child,
    );
  }
}

class _MarkoMenuSurface<T> extends StatelessWidget {
  const _MarkoMenuSurface({
    required this.entries,
    required this.selected,
    required this.header,
    required this.onSelected,
  });

  final List<MarkoMenuEntry<T>> entries;
  final T? selected;
  final String? header;
  final ValueChanged<T> onSelected;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: colors.border),
        boxShadow: [
          BoxShadow(
            color: colors.ink.withValues(alpha: 0.10),
            blurRadius: 24,
            spreadRadius: -4,
            offset: const Offset(0, 12),
          ),
          BoxShadow(
            color: colors.ink.withValues(alpha: 0.05),
            blurRadius: 4,
            offset: const Offset(0, 1),
          ),
        ],
      ),
      padding: const EdgeInsets.all(6),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (header != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(10, 6, 10, 6),
              child: Text(
                header!.toUpperCase(),
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: colors.muted,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 0.6,
                ),
              ),
            ),
          for (final entry in entries) ...[
            if (entry.dividerBefore)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 5),
                child: Divider(height: 1, thickness: 1, color: colors.border),
              ),
            _MarkoMenuRow<T>(
              entry: entry,
              selected: entry.value == selected,
              onTap: () => onSelected(entry.value),
            ),
          ],
        ],
      ),
    );
  }
}

class _MarkoMenuRow<T> extends StatelessWidget {
  const _MarkoMenuRow({
    required this.entry,
    required this.selected,
    required this.onTap,
  });

  final MarkoMenuEntry<T> entry;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final radius = BorderRadius.circular(9);
    final leading = entry.icon != null || entry.avatarText != null;
    return Material(
      color: selected ? colors.brandSoft : Colors.transparent,
      borderRadius: radius,
      child: InkWell(
        borderRadius: radius,
        hoverColor: selected ? Colors.transparent : colors.surfaceMuted,
        onTap: onTap,
        child: Padding(
          padding: EdgeInsets.fromLTRB(leading ? 6 : 10, 7, 8, 7),
          child: Row(
            children: [
              if (leading) ...[
                _MarkoMenuLeading(entry: entry, selected: selected),
                const SizedBox(width: 9),
              ],
              Expanded(
                child: Text(
                  entry.label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: selected ? colors.brand : colors.ink,
                    fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
                  ),
                ),
              ),
              if (entry.trailingLabel != null) ...[
                const SizedBox(width: 8),
                Text(
                  entry.trailingLabel!,
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: selected ? colors.brand : colors.muted,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
              SizedBox(
                width: 22,
                child: selected
                    ? Icon(Icons.check_rounded, size: 16, color: colors.brand)
                    : null,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _MarkoMenuLeading extends StatelessWidget {
  const _MarkoMenuLeading({required this.entry, required this.selected});

  final MarkoMenuEntry entry;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final foreground = selected ? colors.brand : colors.muted;
    return Container(
      width: 26,
      height: 26,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: selected ? colors.surface : colors.surfaceMuted,
        borderRadius: BorderRadius.circular(7),
        border: Border.all(
          color: selected ? colors.brand.withValues(alpha: 0.35) : colors.border,
        ),
      ),
      child: entry.icon != null
          ? Icon(entry.icon, size: 15, color: foreground)
          : Text(
              entry.avatarText!,
              style: Theme.of(context).textTheme.labelSmall?.copyWith(
                color: foreground,
                fontWeight: FontWeight.w700,
              ),
            ),
    );
  }
}
