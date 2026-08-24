import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:heroicons/heroicons.dart';

import 'app_theme.dart';
export 'formatters.dart';

class MarkoWordmark extends StatelessWidget {
  const MarkoWordmark({this.compact = false, this.inverse = false, super.key});

  final bool compact;
  final bool inverse;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final iconBoxSize = compact ? 28.0 : 32.0;
    final innerChartSize = compact
        ? const Size(14.5, 12.5)
        : const Size(16.5, 14.0);
    final strokeWidth = compact ? 1.1 : 1.25;

    final containerColor = inverse
        ? Colors.white.withValues(alpha: 0.12)
        : (isDark ? const Color(0xFF1E1E22) : const Color(0xFF0C0C0E));

    final borderColor = inverse
        ? Colors.white.withValues(alpha: 0.16)
        : (isDark ? const Color(0x2EFFFFFF) : const Color(0x18000000));

    final iconColor = inverse
        ? Colors.white
        : (isDark ? const Color(0xFFF4F4F5) : const Color(0xFFFFFFFF));

    return Row(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Container(
          width: iconBoxSize,
          height: iconBoxSize,
          decoration: BoxDecoration(
            color: containerColor,
            borderRadius: BorderRadius.circular(compact ? 7.0 : 8.5),
            border: Border.all(color: borderColor, width: 1.0),
            boxShadow: inverse
                ? null
                : const [
                    BoxShadow(
                      color: Color(0x14000000),
                      blurRadius: 3,
                      offset: Offset(0, 1),
                    ),
                  ],
          ),
          alignment: Alignment.center,
          child: CustomPaint(
            size: innerChartSize,
            painter: MarkoChartPainter(
              color: iconColor,
              strokeWidth: strokeWidth,
            ),
          ),
        ),
        const SizedBox(width: MarkoSpace.sm),
        Text(
          'Marko',
          style: Theme.of(context).textTheme.titleLarge?.copyWith(
            fontSize: compact ? 17 : 19,
            fontWeight: FontWeight.w700,
            letterSpacing: -0.5,
            color: inverse ? Colors.white : colors.ink,
          ),
        ),
      ],
    );
  }
}

/// Minimalist financial price chart with subtle organic 'M' pulse and breakout dot.
class MarkoChartPainter extends CustomPainter {
  const MarkoChartPainter({required this.color, this.strokeWidth = 1.35});

  final Color color;
  final double strokeWidth;

  @override
  void paint(Canvas canvas, Size size) {
    final linePaint = Paint()
      ..color = color
      ..strokeWidth = strokeWidth
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;

    final dotPaint = Paint()
      ..color = color
      ..style = PaintingStyle.fill;

    final tip = Offset(size.width * 0.90, size.height * 0.16);

    final path = Path()
      ..moveTo(size.width * 0.08, size.height * 0.84)
      ..lineTo(size.width * 0.28, size.height * 0.40)
      ..lineTo(size.width * 0.44, size.height * 0.68)
      ..lineTo(size.width * 0.60, size.height * 0.28)
      ..lineTo(size.width * 0.75, size.height * 0.74)
      ..lineTo(tip.dx, tip.dy);

    canvas.drawPath(path, linePaint);
    canvas.drawCircle(tip, strokeWidth * 0.85, dotPaint);
  }

  @override
  bool shouldRepaint(covariant MarkoChartPainter oldDelegate) {
    return oldDelegate.color != color || oldDelegate.strokeWidth != strokeWidth;
  }
}

/// The shared content column — app bar and page body use the same one.
class MarkoContentFrame extends StatelessWidget {
  const MarkoContentFrame({required this.child, super.key});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(
          maxWidth: MarkoLayout.contentMaxWidth,
        ),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: MarkoLayout.gutter),
          child: child,
        ),
      ),
    );
  }
}

/// The only text field in the app: same height, same 14px ink, same icon size.
/// Everything else comes from `inputDecorationTheme`.
class MarkoTextField extends StatelessWidget {
  const MarkoTextField({
    required this.controller,
    this.hintText,
    this.labelText,
    this.prefixIcon,
    this.prefix,
    this.prefixText,
    this.suffixIcon,
    this.enabled = true,
    this.obscureText = false,
    this.autofocus = false,
    this.keyboardType,
    this.inputFormatters,
    this.textInputAction,
    this.autofillHints,
    this.style,
    this.onChanged,
    this.onSubmitted,
    super.key,
  });

  final TextEditingController controller;
  final String? hintText;
  final String? labelText;
  final HeroIcons? prefixIcon;

  /// Always-visible prefix widget. Unlike [prefixText], it shows while the
  /// field is empty and unfocused.
  final Widget? prefix;
  final String? prefixText;
  final Widget? suffixIcon;
  final bool enabled;
  final bool obscureText;
  final bool autofocus;
  final TextInputType? keyboardType;
  final List<TextInputFormatter>? inputFormatters;
  final TextInputAction? textInputAction;
  final Iterable<String>? autofillHints;
  final TextStyle? style;
  final ValueChanged<String>? onChanged;
  final ValueChanged<String>? onSubmitted;

  @override
  Widget build(BuildContext context) {
    final prefixChild =
        prefix ?? (prefixIcon == null ? null : HeroIcon(prefixIcon!, size: 16));
    final height = MarkoLayout.fieldHeightOf(context);
    final slot = BoxConstraints(minWidth: 34, minHeight: height);
    // InputDecorator installs its own IconButtonTheme *around* the suffix, and
    // `IconButtonTheme.of` prefers that widget over any ThemeData above it — so
    // the opt-out has to sit inside the decoration and copy what it found.
    final suffixChild = suffixIcon == null
        ? null
        : Builder(
            builder: (context) => IconButtonTheme(
              data: IconButtonThemeData(
                style: (IconButtonTheme.of(context).style ?? const ButtonStyle())
                    .copyWith(
                      backgroundColor: const WidgetStatePropertyAll(
                        Colors.transparent,
                      ),
                      shadowColor: const WidgetStatePropertyAll(
                        Colors.transparent,
                      ),
                      elevation: const WidgetStatePropertyAll(0),
                      visualDensity: VisualDensity.compact,
                    ),
              ),
              child: suffixIcon!,
            ),
          );
    return SizedBox(
      height: height,
      child: TextField(
        controller: controller,
        enabled: enabled,
        obscureText: obscureText,
        autofocus: autofocus,
        keyboardType: keyboardType,
        inputFormatters: inputFormatters,
        textInputAction: textInputAction,
        autofillHints: autofillHints,
        style:
            style ??
            Theme.of(context).textTheme.bodyMedium?.copyWith(
              fontSize: MarkoLayout.fieldFontSizeOf(context),
            ),
        textAlignVertical: TextAlignVertical.center,
        onChanged: onChanged,
        onSubmitted: onSubmitted,
        decoration: InputDecoration(
          isDense: true,
          hintText: hintText,
          labelText: labelText,
          contentPadding: const EdgeInsets.symmetric(
            horizontal: MarkoSpace.md,
            vertical: 9.5,
          ),
          prefixIcon: prefixChild == null
              // Center, because prefixIconConstraints stretch the slot to the
              // full field height and the child would else sit at the top.
              ? null
              : Center(
                  widthFactor: 1,
                  child: Padding(
                    padding: const EdgeInsets.only(left: 10, right: 8),
                    child: prefixChild,
                  ),
                ),
          prefixIconConstraints: slot,
          prefixText: prefixText,
          suffixIcon: suffixChild,
          suffixIconConstraints: slot,
        ),
      ),
    );
  }
}

/// Flips the app between the light and dark palettes.
class MarkoThemeToggle extends ConsumerWidget {
  const MarkoThemeToggle({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    return IconButton(
      tooltip: dark ? 'Світла тема' : 'Темна тема',
      onPressed: () => ref
          .read(themeModeProvider.notifier)
          .toggle(Theme.of(context).brightness),
      icon: HeroIcon(dark ? HeroIcons.sun : HeroIcons.moon, size: 18),
    );
  }
}

/// Level 1 surface: 1px hairline plus a single crisp offset shadow.
class MarkoPanel extends StatelessWidget {
  const MarkoPanel({
    required this.child,
    this.padding = const EdgeInsets.all(MarkoSpace.xl),
    this.color,
    this.borderColor,
    this.onTap,
    super.key,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;
  final Color? color;
  final Color? borderColor;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final radius = BorderRadius.circular(colors.panelRadius);
    final content = Padding(padding: padding, child: child);
    return DecoratedBox(
      decoration: BoxDecoration(
        color: color ?? colors.surface,
        borderRadius: radius,
        border: Border.all(color: borderColor ?? colors.border),
        boxShadow: MarkoShadow.card,
      ),
      child: onTap == null
          ? content
          : Material(
              color: Colors.transparent,
              child: InkWell(
                borderRadius: radius,
                onTap: onTap,
                child: content,
              ),
            ),
    );
  }
}

/// Section label above a block of content: mono caption, `faint` ink.
/// Sentence case — the design system never shouts.
class MarkoSectionLabel extends StatelessWidget {
  const MarkoSectionLabel(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Text(text, style: MarkoType.caption.copyWith(color: colors.faint));
  }
}

/// A hairline split by a caption: «—— або через пошту ——».
class MarkoLabelledDivider extends StatelessWidget {
  const MarkoLabelledDivider({required this.label, super.key});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        const Expanded(child: Divider()),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: MarkoSpace.md),
          child: MarkoSectionLabel(label),
        ),
        const Expanded(child: Divider()),
      ],
    );
  }
}

/// Monospaced technical identifier: OEM numbers, article codes, SKUs.
class MarkoOemChip extends StatelessWidget {
  const MarkoOemChip(this.code, {this.tone, super.key});

  final String code;
  final Color? tone;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final ink = tone ?? colors.ink;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: tone == null
            ? colors.surfaceMuted
            : tone!.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(MarkoRadius.xs),
        border: Border.all(
          color: tone == null ? colors.border : tone!.withValues(alpha: 0.24),
        ),
      ),
      child: Text(code, style: MarkoType.oem.copyWith(color: ink)),
    );
  }
}

/// Keycap hint shown next to actionable inputs (`Enter ↵`, `Esc`).
class MarkoHotkey extends StatelessWidget {
  const MarkoHotkey(this.label, {super.key});

  final String label;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(MarkoRadius.xs),
        border: Border.all(color: colors.border),
      ),
      child: Text(label, style: MarkoType.hotkey.copyWith(color: colors.faint)),
    );
  }
}

/// Status pill with optional semantic dot: availability, sync state, quality.
class MarkoStatusPill extends StatelessWidget {
  const MarkoStatusPill({
    required this.label,
    required this.tone,
    this.showDot = false,
    super.key,
  });

  final String label;
  final Color tone;
  final bool showDot;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: MarkoSpace.sm,
        vertical: 4,
      ),
      decoration: BoxDecoration(
        color: tone.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(MarkoRadius.sm),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (showDot) ...[
            Container(
              width: 6,
              height: 6,
              decoration: BoxDecoration(color: tone, shape: BoxShape.circle),
            ),
            const SizedBox(width: 6),
          ],
          Flexible(
            child: Text(
              label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(
                context,
              ).textTheme.labelMedium?.copyWith(
                color: tone,
                fontWeight: FontWeight.w500,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

enum MarkoMessageTone { info, success, warning, error }

class MarkoInlineMessage extends StatelessWidget {
  const MarkoInlineMessage({
    required this.message,
    this.tone = MarkoMessageTone.info,
    this.action,
    super.key,
  });

  final String message;
  final MarkoMessageTone tone;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final (foreground, background, icon) = switch (tone) {
      MarkoMessageTone.info => (
        colors.brand,
        colors.brandSoft,
        HeroIcons.informationCircle,
      ),
      MarkoMessageTone.success => (
        colors.positive,
        colors.positiveSoft,
        HeroIcons.checkCircle,
      ),
      MarkoMessageTone.warning => (
        colors.warning,
        colors.warningSoft,
        HeroIcons.exclamationTriangle,
      ),
      MarkoMessageTone.error => (
        colors.negative,
        colors.negativeSoft,
        HeroIcons.exclamationCircle,
      ),
    };
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: MarkoSpace.md,
        vertical: MarkoSpace.md,
      ),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(MarkoRadius.lg),
        border: Border.all(color: foreground.withValues(alpha: 0.18)),
      ),
      child: Row(
        children: [
          HeroIcon(icon, size: 17, color: foreground),
          const SizedBox(width: MarkoSpace.sm),
          Expanded(
            child: Text(
              message,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: foreground,
                fontWeight: FontWeight.w500,
              ),
            ),
          ),
          if (action != null) ...[
            const SizedBox(width: MarkoSpace.sm),
            action!,
          ],
        ],
      ),
    );
  }
}

/// Standard empty state card across the app: icon inside a rounded surface,
/// bold title, description, and optional action button.
class MarkoEmptyState extends StatelessWidget {
  const MarkoEmptyState({
    required this.icon,
    required this.title,
    required this.description,
    this.action,
    this.compact = false,
    this.maxWidth = 440,
    super.key,
  });

  final HeroIcons icon;
  final String title;
  final String description;
  final Widget? action;
  final bool compact;
  final double maxWidth;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final iconBoxSize = compact ? 36.0 : 44.0;
    final iconSize = compact ? 18.0 : 22.0;

    return ConstrainedBox(
      constraints: BoxConstraints(maxWidth: maxWidth),
      child: MarkoPanel(
        padding: EdgeInsets.symmetric(
          horizontal: compact ? MarkoSpace.lg : MarkoSpace.xxl,
          vertical: compact ? MarkoSpace.xl : MarkoSpace.huge,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Container(
              width: iconBoxSize,
              height: iconBoxSize,
              decoration: BoxDecoration(
                color: colors.surfaceMuted,
                borderRadius: BorderRadius.circular(
                  compact ? MarkoRadius.md : MarkoRadius.lg,
                ),
              ),
              alignment: Alignment.center,
              child: HeroIcon(
                icon,
                color: colors.faint,
                size: iconSize,
              ),
            ),
            SizedBox(height: compact ? MarkoSpace.sm : MarkoSpace.md),
            Text(
              title,
              textAlign: TextAlign.center,
              style: (compact
                      ? Theme.of(context).textTheme.titleSmall
                      : Theme.of(context).textTheme.titleMedium)
                  ?.copyWith(fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: MarkoSpace.xs),
            Text(
              description,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: colors.muted,
                  ),
            ),
            if (action != null) ...[
              SizedBox(height: compact ? MarkoSpace.md : MarkoSpace.lg),
              action!,
            ],
          ],
        ),
      ),
    );
  }
}

/// Formats raw digit input with thousand space separators (e.g. 1 000 000).
class ThousandsPriceInputFormatter extends TextInputFormatter {
  const ThousandsPriceInputFormatter();

  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    if (newValue.text.isEmpty) {
      return newValue;
    }

    final text = newValue.text;
    final parts = text.replaceAll(' ', '').split(RegExp(r'[,.]'));
    final integerPart = parts[0].replaceAll(RegExp(r'[^\d]'), '');

    if (integerPart.isEmpty && parts.length == 1) {
      return const TextEditingValue(text: '');
    }

    final formattedInt = integerPart.replaceAllMapped(
      RegExp(r'\B(?=(\d{3})+(?!\d))'),
      (match) => ' ',
    );

    String formatted = formattedInt;
    if (parts.length > 1) {
      final sep = text.contains(',') ? ',' : '.';
      final decimalPart = parts
          .sublist(1)
          .join()
          .replaceAll(RegExp(r'[^\d]'), '');
      formatted = '$formattedInt$sep$decimalPart';
    }

    final nonSpaceBeforeCursor =
        newValue.selection.end > 0 && newValue.selection.end <= text.length
        ? text.substring(0, newValue.selection.end).replaceAll(' ', '').length
        : text.replaceAll(' ', '').length;

    var newCursorPos = 0;
    var nonSpaceCount = 0;
    for (int i = 0; i < formatted.length; i++) {
      if (nonSpaceCount == nonSpaceBeforeCursor) {
        break;
      }
      if (formatted[i] != ' ') {
        nonSpaceCount++;
      }
      newCursorPos = i + 1;
    }

    return TextEditingValue(
      text: formatted,
      selection: TextSelection.collapsed(
        offset: newCursorPos.clamp(0, formatted.length),
      ),
    );
  }
}

/// The one modal shell in the app: a bottom sheet on phones, a centered
/// dialog above that. Everything overlaying the catalog goes through here.
Future<void> showMarkoModal(
  BuildContext context, {
  HeroIcons? icon,
  Color? accent,
  required String title,
  String? subtitle,
  required Widget child,
}) {
  final header = _ModalHeader(
    icon: icon,
    accent: accent,
    title: title,
  );
  if (MediaQuery.sizeOf(context).width < 700) {
    return showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => _Sheet(header: header, child: child),
    );
  }
  return showDialog<void>(
    context: context,
    barrierDismissible: true,
    builder: (context) => _Dialog(header: header, child: child),
  );
}

class _Dialog extends StatelessWidget {
  const _Dialog({required this.header, required this.child});

  final Widget header;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Dialog(
      backgroundColor: Colors.transparent,
      insetPadding: const EdgeInsets.symmetric(
        horizontal: MarkoSpace.lg,
        vertical: MarkoSpace.xl,
      ),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520, maxHeight: 840),
        child: Container(
          decoration: BoxDecoration(
            color: colors.surface,
            borderRadius: BorderRadius.circular(MarkoRadius.xl),
            border: Border.all(color: colors.border),
            boxShadow: MarkoShadow.overlay,
          ),
          clipBehavior: Clip.antiAlias,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              header,
              const Divider(height: 1),
              Flexible(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.all(MarkoSpace.xl),
                  child: child,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Sheet extends StatelessWidget {
  const _Sheet({required this.header, required this.child});

  final Widget header;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      constraints: BoxConstraints(
        maxHeight: MediaQuery.sizeOf(context).height * 0.88,
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
          header,
          const Divider(height: 1),
          Flexible(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(MarkoSpace.lg),
              child: child,
            ),
          ),
        ],
      ),
    );
  }
}

class _ModalHeader extends StatelessWidget {
  const _ModalHeader({
    this.icon,
    this.accent,
    required this.title,
  });

  final HeroIcons? icon;
  final Color? accent;
  final String title;

  @override
  Widget build(BuildContext context) {
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
              title,
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
}
