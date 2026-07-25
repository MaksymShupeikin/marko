import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/app_language.dart';
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
              _register
                  ? context.localized(
                      ru: 'Создайте аккаунт',
                      uk: 'Створіть обліковий запис',
                    )
                  : context.localized(
                      ru: 'С возвращением',
                      uk: 'З поверненням',
                    ),
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            const SizedBox(height: 8),
            Text(
              _register
                  ? context.localized(
                      ru: 'Подключите магазины и держите цены под контролем.',
                      uk: 'Підключіть магазини та тримайте ціни під контролем.',
                    )
                  : context.localized(
                      ru: 'Войдите, чтобы продолжить работу с ценами.',
                      uk: 'Увійдіть, щоб продовжити роботу з цінами.',
                    ),
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
                label: Text(
                  context.localized(
                    ru: 'Продолжить с Google',
                    uk: 'Продовжити з Google',
                  ),
                ),
              ),
            if (!showGoogle)
              MarkoInlineMessage(
                message: context.localized(
                  ru:
                      'Google-вход недоступен в нативной Windows-версии. '
                      'Используйте web/PWA или войдите по почте.',
                  uk:
                      'Вхід через Google недоступний у нативній Windows-версії. '
                      'Використовуйте web/PWA або увійдіть через пошту.',
                ),
                tone: MarkoMessageTone.warning,
              ),
            const SizedBox(height: 22),
            Row(
              children: [
                const Expanded(child: Divider()),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  child: Text(
                    context.localized(
                      ru: 'или по почте',
                      uk: 'або через пошту',
                    ),
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
              decoration: InputDecoration(
                labelText: context.localized(ru: 'Почта', uk: 'Пошта'),
                hintText: 'name@company.com',
                prefixIcon: const Icon(Icons.alternate_email_rounded, size: 20),
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
                labelText: context.localized(ru: 'Пароль', uk: 'Пароль'),
                prefixIcon: const Icon(Icons.lock_outline_rounded, size: 20),
                suffixIcon: IconButton(
                  tooltip: _obscurePassword
                      ? context.localized(
                          ru: 'Показать пароль',
                          uk: 'Показати пароль',
                        )
                      : context.localized(
                          ru: 'Скрыть пароль',
                          uk: 'Приховати пароль',
                        ),
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
              label: _register
                  ? context.localized(
                      ru: 'Создать аккаунт',
                      uk: 'Створити обліковий запис',
                    )
                  : context.localized(ru: 'Войти', uk: 'Увійти'),
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
                    ? context.localized(
                        ru: 'Уже есть аккаунт? Войти',
                        uk: 'Уже є обліковий запис? Увійти',
                      )
                    : context.localized(
                        ru: 'Нет аккаунта? Зарегистрироваться',
                        uk: 'Немає облікового запису? Зареєструватися',
                      ),
              ),
            ),
            const SizedBox(height: 12),
            Text(
              context.localized(
                ru: 'Авторизация защищена Firebase. Данные магазинов хранятся в Marko.',
                uk: 'Авторизацію захищено Firebase. Дані магазинів зберігаються в Marko.',
              ),
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
            context.localized(
              ru: 'Цены под\nконтролем.',
              uk: 'Ціни під\nконтролем.',
            ),
            style: Theme.of(context).textTheme.displaySmall?.copyWith(
              color: Colors.white,
              fontSize: 42,
            ),
          ),
          const SizedBox(height: 18),
          Text(
            context.localized(
              ru:
                  'Следите за конкурентами, находите расхождения и принимайте '
                  'решения на основе актуальных данных.',
              uk:
                  'Стежте за конкурентами, знаходьте розбіжності та ухвалюйте '
                  'рішення на основі актуальних даних.',
            ),
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
