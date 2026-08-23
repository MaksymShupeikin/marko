import 'package:flutter/material.dart';
import 'package:heroicons/heroicons.dart';
import 'package:toastification/toastification.dart';

import '../app_theme.dart';
import '../marko_ui.dart' show MarkoMessageTone;

/// Phones get a full-width banner under the status bar, everything wider gets
/// a card in the top-right corner. Same breakpoint as [showMarkoModal].
const _phoneWidth = 700.0;

/// App-wide toast config — install it once under [MaterialApp], where there
/// is a [MediaQuery] to size it against.
///
/// The overlay column is exactly as wide as the toasts: it sits above the
/// page and swallows taps, so a screen-wide column would block the whole
/// top strip of the app.
ToastificationConfig markoToastConfig(BuildContext context) {
  final width = MediaQuery.sizeOf(context).width;
  return ToastificationConfig(
    itemWidth: width < _phoneWidth ? width : _cardWidth + MarkoSpace.xl,
    marginBuilder: _toastMargin,
    animationDuration: const Duration(milliseconds: 280),
    maxToastLimit: 3,
  );
}

const _cardWidth = 400.0;

EdgeInsetsGeometry _toastMargin(BuildContext context, AlignmentGeometry _) =>
    EdgeInsets.only(top: MediaQuery.paddingOf(context).top + MarkoSpace.sm);

/// The one notification surface in the app. Call it before popping a route —
/// the toast itself outlives the caller, it lives in the root overlay.
void showMarkoToast(
  BuildContext context, {
  required String message,
  String? title,
  MarkoMessageTone tone = MarkoMessageTone.success,
  Duration duration = const Duration(seconds: 4),
}) {
  final phone = MediaQuery.sizeOf(context).width < _phoneWidth;
  toastification.showCustom(
    context: context,
    alignment: phone ? Alignment.topCenter : Alignment.topRight,
    autoCloseDuration: duration,
    builder: (_, item) => _MarkoToastCard(
      item: item,
      message: message,
      title: title,
      tone: tone,
      phone: phone,
    ),
  );
}

class _MarkoToastCard extends StatelessWidget {
  const _MarkoToastCard({
    required this.item,
    required this.message,
    required this.title,
    required this.tone,
    required this.phone,
  });

  final ToastificationItem item;
  final String message;
  final String? title;
  final MarkoMessageTone tone;
  final bool phone;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final (accent, soft, icon) = switch (tone) {
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

    final card = Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(MarkoRadius.lg),
        onTap: () => toastification.dismiss(item),
        child: Container(
          clipBehavior: Clip.antiAlias,
          decoration: BoxDecoration(
            color: colors.surface,
            borderRadius: BorderRadius.circular(MarkoRadius.lg),
            border: Border.all(color: colors.border),
            boxShadow: MarkoShadow.overlay,
          ),
          child: IntrinsicHeight(
            child: Padding(
              padding: const EdgeInsets.symmetric(
                horizontal: MarkoSpace.md,
                vertical: MarkoSpace.md,
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  Container(
                    width: 28,
                    height: 28,
                    decoration: BoxDecoration(
                      color: soft,
                      shape: BoxShape.circle,
                    ),
                    alignment: Alignment.center,
                    child: HeroIcon(icon, size: 16, color: accent),
                  ),
                  const SizedBox(width: MarkoSpace.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        if (title != null) ...[
                          Text(
                            title!,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: Theme.of(context).textTheme.bodyMedium
                                ?.copyWith(
                                  fontWeight: FontWeight.w600,
                                  color: colors.ink,
                                ),
                          ),
                          const SizedBox(height: 2),
                        ],
                        Text(
                          message,
                          maxLines: 4,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context).textTheme.bodySmall
                              ?.copyWith(
                                color: title == null
                                    ? colors.ink
                                    : colors.muted,
                                height: 1.35,
                              ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: MarkoSpace.sm),
                  InkResponse(
                    onTap: () => toastification.dismiss(item),
                    radius: 16,
                    child: HeroIcon(
                      HeroIcons.xMark,
                      size: 15,
                      color: colors.faint,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );

    return Padding(
      padding: phone
          ? const EdgeInsets.fromLTRB(
              MarkoSpace.sm,
              0,
              MarkoSpace.sm,
              MarkoSpace.sm,
            )
          : const EdgeInsets.only(
              right: MarkoSpace.xl,
              bottom: MarkoSpace.sm,
            ),
      child: card,
    );
  }
}
