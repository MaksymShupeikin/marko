import 'package:flutter/material.dart';
import 'package:heroicons/heroicons.dart';

import '../app_theme.dart';
import '../marko_ui.dart';
import 'marko_button.dart';

/// Shared confirmation dialog for destructive catalog actions.
///
/// Product, store, file and bulk deletion use the same hierarchy: action icon,
/// affected entity, a short consequence and the standard Marko danger button.
class MarkoConfirmationDialog extends StatelessWidget {
  const MarkoConfirmationDialog({
    required this.title,
    required this.subject,
    required this.description,
    required this.confirmLabel,
    required this.onConfirm,
    this.subjectDetails,
    this.cancelLabel = 'Скасувати',
    this.icon = HeroIcons.trash,
    this.subjectIcon = HeroIcons.archiveBox,
    this.loading = false,
    this.error,
    super.key,
  });

  final String title;
  final String subject;
  final String? subjectDetails;
  final String description;
  final String confirmLabel;
  final String cancelLabel;
  final HeroIcons icon;
  final HeroIcons subjectIcon;
  final VoidCallback onConfirm;
  final bool loading;
  final String? error;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return AlertDialog(
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(colors.panelRadius),
        side: BorderSide(color: colors.border),
      ),
      backgroundColor: colors.surface,
      surfaceTintColor: Colors.transparent,
      icon: Container(
        width: 44,
        height: 44,
        decoration: BoxDecoration(
          color: colors.negative.withValues(alpha: 0.10),
          shape: BoxShape.circle,
        ),
        alignment: Alignment.center,
        child: HeroIcon(icon, color: colors.negative, size: 22),
      ),
      title: Text(
        title,
        style: Theme.of(context).textTheme.titleMedium?.copyWith(
          fontWeight: FontWeight.w600,
          fontSize: 18,
        ),
      ),
      content: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 380),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              decoration: BoxDecoration(
                color: colors.surfaceMuted,
                borderRadius: BorderRadius.circular(MarkoRadius.md),
                border: Border.all(color: colors.border),
              ),
              child: Row(
                children: [
                  Container(
                    width: 32,
                    height: 32,
                    decoration: BoxDecoration(
                      color: colors.negativeSoft,
                      shape: BoxShape.circle,
                      border: Border.all(
                        color: colors.negative.withValues(alpha: 0.24),
                      ),
                    ),
                    alignment: Alignment.center,
                    child: HeroIcon(
                      subjectIcon,
                      size: 16,
                      color: colors.negative,
                    ),
                  ),
                  const SizedBox(width: MarkoSpace.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          subject,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context).textTheme.bodyMedium
                              ?.copyWith(fontWeight: FontWeight.w600),
                        ),
                        if (subjectDetails != null &&
                            subjectDetails!.trim().isNotEmpty)
                          Text(
                            subjectDetails!,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: MarkoType.caption.copyWith(
                              color: colors.faint,
                              fontSize: 11.5,
                            ),
                          ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: MarkoSpace.md),
            Text(
              description,
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: colors.muted),
            ),
            if (error != null) ...[
              const SizedBox(height: MarkoSpace.md),
              MarkoInlineMessage(message: error!, tone: MarkoMessageTone.error),
            ],
          ],
        ),
      ),
      actionsPadding: const EdgeInsets.fromLTRB(
        MarkoSpace.lg,
        0,
        MarkoSpace.lg,
        MarkoSpace.lg,
      ),
      actions: [
        TextButton(
          onPressed: loading ? null : () => Navigator.of(context).pop(false),
          child: Text(cancelLabel),
        ),
        MarkoButton.danger(
          label: confirmLabel,
          icon: icon,
          loading: loading,
          onPressed: loading ? null : onConfirm,
        ),
      ],
    );
  }
}

Future<bool> confirmMarkoAction(
  BuildContext context, {
  required String title,
  required String subject,
  required String description,
  required String confirmLabel,
  String? subjectDetails,
  String cancelLabel = 'Скасувати',
  HeroIcons icon = HeroIcons.trash,
  HeroIcons subjectIcon = HeroIcons.archiveBox,
  bool barrierDismissible = true,
}) async {
  return await showDialog<bool>(
        context: context,
        barrierDismissible: barrierDismissible,
        builder: (context) => MarkoConfirmationDialog(
          title: title,
          subject: subject,
          subjectDetails: subjectDetails,
          description: description,
          confirmLabel: confirmLabel,
          cancelLabel: cancelLabel,
          icon: icon,
          subjectIcon: subjectIcon,
          onConfirm: () => Navigator.of(context).pop(true),
        ),
      ) ??
      false;
}
