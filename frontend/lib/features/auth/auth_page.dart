import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/app_theme.dart';
import '../../core/environment.dart';
import '../../core/marko_ui.dart';
import '../../core/widgets/marko_button.dart';
import 'auth_controller.dart';
import 'auth_models.dart';

class AuthPage extends ConsumerStatefulWidget {
  const AuthPage({super.key});

  @override
  ConsumerState<AuthPage> createState() => _AuthPageState();
}

class _AuthPageState extends ConsumerState<AuthPage> {
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _register = false;
  bool _obscurePassword = true;

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final asyncAuth = ref.watch(authControllerProvider);
    final auth = asyncAuth.value;
    final busy = asyncAuth.isLoading || auth?.busy == true;

    return Scaffold(
      body: GestureDetector(
        onTap: () => FocusManager.instance.primaryFocus?.unfocus(),
        child: LayoutBuilder(
          builder: (context, constraints) {
            final wide = constraints.maxWidth >= 960;
            if (!wide) {
              return _MobileAuthLayout(form: _buildForm(context, auth, busy));
            }
            return Row(
              children: [
                const Expanded(flex: 9, child: _AuthStory()),
                Expanded(
                  flex: 11,
                  child: Center(
                    child: SingleChildScrollView(
                      padding: const EdgeInsets.all(48),
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 430),
                        child: _buildForm(context, auth, busy),
                      ),
                    ),
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }

  Widget _buildForm(BuildContext context, MarkoAuthState? auth, bool busy) {
    final colors = MarkoTheme.of(context);
    final showGoogle = Environment.supportsGoogleSignIn;
    return MarkoPanel(
      padding: const EdgeInsets.all(28),
      child: AutofillGroup(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              _register ? 'Создайте аккаунт' : 'С возвращением',
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            const SizedBox(height: 8),
            Text(
              _register
                  ? 'Подключите магазины и держите цены под контролем.'
                  : 'Войдите, чтобы продолжить работу с ценами.',
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(color: colors.muted),
            ),
            const SizedBox(height: 24),
            if (showGoogle)
              OutlinedButton.icon(
                onPressed: busy
                    ? null
                    : () => ref
                          .read(authControllerProvider.notifier)
                          .loginWithGoogle(),
                icon: Container(
                  width: 22,
                  height: 22,
                  decoration: BoxDecoration(
                    color: colors.surfaceMuted,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  alignment: Alignment.center,
                  child: Text(
                    'G',
                    style: Theme.of(context).textTheme.labelLarge?.copyWith(
                      color: colors.brand,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                label: const Text('Продолжить с Google'),
              ),
            if (!showGoogle)
              const MarkoInlineMessage(
                message:
                    'Google-вход недоступен в нативной Windows-версии. '
                    'Используйте web/PWA или войдите по почте.',
                tone: MarkoMessageTone.warning,
              ),
            const SizedBox(height: 22),
            Row(
              children: [
                const Expanded(child: Divider()),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  child: Text(
                    'или по почте',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ),
                const Expanded(child: Divider()),
              ],
            ),
            const SizedBox(height: 22),
            TextField(
              controller: _emailController,
              enabled: !busy,
              keyboardType: TextInputType.emailAddress,
              autofillHints: const [AutofillHints.email],
              decoration: const InputDecoration(
                labelText: 'Почта',
                hintText: 'name@company.com',
                prefixIcon: Icon(Icons.alternate_email_rounded, size: 20),
              ),
            ),
            const SizedBox(height: 14),
            TextField(
              controller: _passwordController,
              enabled: !busy,
              obscureText: _obscurePassword,
              autofillHints: _register
                  ? const [AutofillHints.newPassword]
                  : const [AutofillHints.password],
              onSubmitted: (_) => busy ? null : _submit(),
              decoration: InputDecoration(
                labelText: 'Пароль',
                prefixIcon: const Icon(Icons.lock_outline_rounded, size: 20),
                suffixIcon: IconButton(
                  tooltip: _obscurePassword
                      ? 'Показать пароль'
                      : 'Скрыть пароль',
                  onPressed: () =>
                      setState(() => _obscurePassword = !_obscurePassword),
                  icon: Icon(
                    _obscurePassword
                        ? Icons.visibility_outlined
                        : Icons.visibility_off_outlined,
                    size: 20,
                  ),
                ),
              ),
            ),
            if (auth?.error != null) ...[
              const SizedBox(height: 14),
              MarkoInlineMessage(
                message: auth!.error!,
                tone: MarkoMessageTone.error,
              ),
            ],
            if (auth?.notice != null) ...[
              const SizedBox(height: 14),
              MarkoInlineMessage(
                message: auth!.notice!,
                tone: MarkoMessageTone.success,
              ),
            ],
            const SizedBox(height: 18),
            MarkoButton(
              label: _register ? 'Создать аккаунт' : 'Войти',
              onPressed: busy ? null : _submit,
              loading: busy,
              expand: true,
            ),
            const SizedBox(height: 8),
            TextButton(
              onPressed: busy
                  ? null
                  : () => setState(() => _register = !_register),
              child: Text(
                _register
                    ? 'Уже есть аккаунт? Войти'
                    : 'Нет аккаунта? Зарегистрироваться',
              ),
            ),
            const SizedBox(height: 12),
            Text(
              'Авторизация защищена Firebase. Данные магазинов хранятся в Marko.',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }

  void _submit() {
    FocusManager.instance.primaryFocus?.unfocus();
    final controller = ref.read(authControllerProvider.notifier);
    if (_register) {
      controller.register(_emailController.text, _passwordController.text);
    } else {
      controller.login(_emailController.text, _passwordController.text);
    }
  }
}

class _MobileAuthLayout extends StatelessWidget {
  const _MobileAuthLayout({required this.form});

  final Widget form;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 28),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 440),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [const MarkoWordmark(), const SizedBox(height: 28), form],
          ),
        ),
      ),
    );
  }
}

class _AuthStory extends StatelessWidget {
  const _AuthStory();

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      margin: const EdgeInsets.all(16),
      padding: const EdgeInsets.all(48),
      decoration: BoxDecoration(
        color: colors.ink,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const MarkoWordmark(inverse: true),
          const Spacer(),
          Text(
            'Цены под\nконтролем.',
            style: Theme.of(context).textTheme.displaySmall?.copyWith(
              color: Colors.white,
              fontSize: 42,
            ),
          ),
          const SizedBox(height: 18),
          Text(
            'Следите за конкурентами, находите расхождения и принимайте '
            'решения на основе актуальных данных.',
            style: Theme.of(context).textTheme.bodyLarge?.copyWith(
              color: Colors.white.withValues(alpha: 0.7),
            ),
          ),
          const SizedBox(height: 32),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.08),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: Colors.white.withValues(alpha: 0.12)),
            ),
            child: const Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.bolt_rounded, size: 16, color: Colors.white),
                SizedBox(width: 7),
                Text(
                  'Prom monitoring workspace',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
