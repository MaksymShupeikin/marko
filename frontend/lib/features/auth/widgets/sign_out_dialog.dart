import 'package:flutter/material.dart';
import 'package:heroicons/heroicons.dart';

import '../../../core/app_theme.dart';
import '../../../core/widgets/marko_button.dart';
import '../auth_models.dart';

Future<bool> confirmSignOut(
  BuildContext context, {
  required AuthUser user,
}) async {
  return await showDialog<bool>(
        context: context,
        barrierDismissible: true,
        builder: (context) => _SignOutDialog(user: user),
      ) ??
      false;
}

class _SignOutDialog extends StatelessWidget {
  const _SignOutDialog({required this.user});

  final AuthUser user;

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
          color: colors.brand.withValues(alpha: 0.10),
          shape: BoxShape.circle,
        ),
        alignment: Alignment.center,
        child: HeroIcon(
          HeroIcons.arrowRightStartOnRectangle,
          color: colors.ink,
          size: 22,
        ),
      ),
      title: Text(
        'Вийти з акаунта?',
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
                      color: colors.brandSoft,
                      shape: BoxShape.circle,
                      border: Border.all(
                        color: colors.brand.withValues(alpha: 0.24),
                      ),
                    ),
                    alignment: Alignment.center,
                    child: HeroIcon(
                      HeroIcons.user,
                      size: 16,
                      color: colors.brand,
                    ),
                  ),
                  const SizedBox(width: MarkoSpace.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          user.shortName,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                                fontWeight: FontWeight.w600,
                              ),
                        ),
                        Text(
                          user.email,
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
              'Ви зможете в будь-який момент повернутися та увійти знову.',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: colors.muted,
                  ),
            ),
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
          onPressed: () => Navigator.of(context).pop(false),
          child: const Text('Скасувати'),
        ),
        MarkoButton(
          label: 'Вийти',
          icon: HeroIcons.arrowRightStartOnRectangle,
          onPressed: () => Navigator.of(context).pop(true),
        ),
      ],
    );
  }
}
