import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:heroicons/heroicons.dart';

import '../../core/app_theme.dart';
import '../../core/firebase_auth_client.dart';
import '../../core/marko_ui.dart';
import '../../core/widgets/marko_button.dart';
import '../../core/widgets/marko_loader.dart';

/// Landing page for Firebase email action links. The console action URL
/// points at markoprice.com, so both mode=resetPassword and mode=verifyEmail
/// arrive here with a one-time oobCode.
class ResetPasswordPage extends ConsumerStatefulWidget {
  const ResetPasswordPage({
    super.key,
    required this.mode,
    required this.oobCode,
  });

  final String mode;
  final String oobCode;

  @override
  ConsumerState<ResetPasswordPage> createState() => _ResetPasswordPageState();
}

class _ResetPasswordPageState extends ConsumerState<ResetPasswordPage> {
  final _passwordController = TextEditingController();
  final _confirmController = TextEditingController();
  bool _obscurePassword = true;
  bool _busy = true;
  bool _done = false;
  String? _email;
  String? _error;

  bool get _verifyEmailMode => widget.mode == 'verifyEmail';

  @override
  void initState() {
    super.initState();
    _verifyLink();
  }

  @override
  void dispose() {
    _passwordController.dispose();
    _confirmController.dispose();
    super.dispose();
  }

  Future<void> _verifyLink() async {
    final auth = ref.read(authClientProvider);
    try {
      if (widget.oobCode.isEmpty) {
        throw const AuthClientException(
          'Посилання неповне. Відкрийте його з листа ще раз.',
        );
      }
      if (_verifyEmailMode) {
        await auth.applyActionCode(widget.oobCode);
        if (!mounted) return;
        setState(() {
          _busy = false;
          _done = true;
        });
      } else {
        final email = await auth.verifyPasswordResetCode(widget.oobCode);
        if (!mounted) return;
        setState(() {
          _busy = false;
          _email = email;
        });
      }
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = _message(error);
      });
    }
  }

  Future<void> _submit() async {
    FocusManager.instance.primaryFocus?.unfocus();
    final password = _passwordController.text;
    if (password.length < 8) {
      setState(() => _error = 'Пароль має містити щонайменше 8 символів');
      return;
    }
    if (password != _confirmController.text) {
      setState(() => _error = 'Паролі не збігаються');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref
          .read(authClientProvider)
          .confirmPasswordReset(widget.oobCode, password);
      if (!mounted) return;
      setState(() {
        _busy = false;
        _done = true;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = _message(error);
      });
    }
  }

  String _message(Object error) {
    if (error is AuthClientException) return error.message;
    return error.toString().replaceFirst('Exception: ', '');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 28),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 440),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Row(
                  children: [MarkoWordmark(), Spacer(), MarkoThemeToggle()],
                ),
                const SizedBox(height: MarkoSpace.xxl),
                MarkoPanel(
                  padding: const EdgeInsets.all(MarkoSpace.xxl),
                  child: _buildContent(context),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildContent(BuildContext context) {
    final colors = MarkoTheme.of(context);

    if (_busy && _email == null && !_done) {
      return const Padding(
        padding: EdgeInsets.all(MarkoSpace.xxl),
        child: Center(child: MarkoLoader(size: 22)),
      );
    }

    if (_done) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          MarkoInlineMessage(
            message: _verifyEmailMode
                ? 'Пошту підтверджено. Тепер можете увійти.'
                : 'Пароль змінено. Увійдіть з новим паролем.',
            tone: MarkoMessageTone.success,
          ),
          const SizedBox(height: MarkoSpace.lg),
          MarkoButton(
            label: 'Увійти',
            onPressed: () => context.go('/login'),
            expand: true,
          ),
        ],
      );
    }

    if (_email == null) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          MarkoInlineMessage(
            message: _error ?? 'Посилання недійсне.',
            tone: MarkoMessageTone.error,
          ),
          const SizedBox(height: MarkoSpace.lg),
          MarkoButton(
            label: 'До входу',
            onPressed: () => context.go('/login'),
            expand: true,
          ),
        ],
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('Новий пароль', style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: MarkoSpace.sm),
        Text(
          'Встановіть новий пароль для $_email',
          style: Theme.of(
            context,
          ).textTheme.bodyMedium?.copyWith(color: colors.muted),
        ),
        const SizedBox(height: MarkoSpace.xxl),
        MarkoTextField(
          controller: _passwordController,
          enabled: !_busy,
          obscureText: _obscurePassword,
          autofillHints: const [AutofillHints.newPassword],
          labelText: 'Новий пароль',
          prefixIcon: HeroIcons.lockClosed,
          suffixIcon: IconButton(
            tooltip: _obscurePassword ? 'Показати пароль' : 'Сховати пароль',
            onPressed: () =>
                setState(() => _obscurePassword = !_obscurePassword),
            icon: HeroIcon(
              _obscurePassword ? HeroIcons.eye : HeroIcons.eyeSlash,
              size: 18,
            ),
          ),
        ),
        const SizedBox(height: MarkoSpace.md),
        MarkoTextField(
          controller: _confirmController,
          enabled: !_busy,
          obscureText: _obscurePassword,
          onSubmitted: (_) => _busy ? null : _submit(),
          labelText: 'Повторіть пароль',
          prefixIcon: HeroIcons.lockClosed,
        ),
        if (_error != null) ...[
          const SizedBox(height: MarkoSpace.md),
          MarkoInlineMessage(message: _error!, tone: MarkoMessageTone.error),
        ],
        const SizedBox(height: MarkoSpace.lg),
        MarkoButton(
          label: 'Зберегти пароль',
          onPressed: _busy ? null : _submit,
          loading: _busy,
          expand: true,
        ),
      ],
    );
  }
}
