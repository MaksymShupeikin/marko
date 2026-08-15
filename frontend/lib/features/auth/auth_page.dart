import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/app_language.dart';
import '../../core/app_theme.dart';
import '../../core/environment.dart';
import '../../core/marko_motion.dart';
import '../../core/marko_ui.dart';
import '../../core/widgets/marko_atmosphere.dart';
import '../../core/widgets/marko_button.dart';
import '../../core/widgets/marko_spotlight.dart';
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
      body: MarkoAtmosphere(
        beams: true,
        child: GestureDetector(
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
                          child: MarkoFadeUp(
                            child: _buildForm(context, auth, busy),
                          ),
                        ),
                      ),
                    ),
                  ),
                ],
              );
            },
          ),
        ),
      ),
    );
  }

  Widget _buildForm(BuildContext context, MarkoAuthState? auth, bool busy) {
    final colors = MarkoTheme.of(context);
    final showGoogle = Environment.supportsGoogleSignIn;
    final title = _register
        ? context.localized(
            ru: 'Создайте аккаунт',
            uk: 'Створіть обліковий запис',
          )
        : context.localized(ru: 'С возвращением', uk: 'З поверненням');
    return MarkoMovingBorder(
      radius: colors.panelRadius,
      child: MarkoSpotlight(
        borderRadius: BorderRadius.circular(colors.panelRadius),
        child: MarkoPanel(
          padding: const EdgeInsets.all(28),
          child: AutofillGroup(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                AnimatedSwitcher(
                  duration: const Duration(milliseconds: 280),
                  switchInCurve: Curves.easeOutCubic,
                  switchOutCurve: Curves.easeInCubic,
                  child: Text(
                    title,
                    key: ValueKey(title),
                    style: Theme.of(context).textTheme.headlineSmall,
                  ),
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
                  OutlinedButton(
                    onPressed: busy
                        ? null
                        : () => ref
                              .read(authControllerProvider.notifier)
                              .loginWithGoogle(),
                    child: Wrap(
                      alignment: WrapAlignment.center,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      spacing: 9,
                      runSpacing: 4,
                      children: [
                        Container(
                          width: 22,
                          height: 22,
                          decoration: BoxDecoration(
                            color: colors.surfaceMuted,
                            borderRadius: BorderRadius.circular(6),
                          ),
                          alignment: Alignment.center,
                          child: Text(
                            'G',
                            style: Theme.of(context).textTheme.labelLarge
                                ?.copyWith(
                                  color: colors.brand,
                                  fontWeight: FontWeight.w700,
                                ),
                          ),
                        ),
                        Text(
                          context.localized(
                            ru: 'Продолжить с Google',
                            uk: 'Продовжити з Google',
                          ),
                          textAlign: TextAlign.center,
                        ),
                      ],
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
                    Flexible(
                      child: Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 12),
                        child: Text(
                          context.localized(
                            ru: 'или по почте',
                            uk: 'або через пошту',
                          ),
                          textAlign: TextAlign.center,
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
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
                    prefixIcon: const Icon(
                      Icons.alternate_email_rounded,
                      size: 20,
                    ),
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
                    prefixIcon: const Icon(
                      Icons.lock_outline_rounded,
                      size: 20,
                    ),
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
                    message: _localizedAuthFeedback(context, auth!.error!),
                    tone: MarkoMessageTone.error,
                  ),
                ],
                if (auth?.notice != null) ...[
                  const SizedBox(height: 14),
                  MarkoInlineMessage(
                    message: _localizedAuthFeedback(context, auth!.notice!),
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

String _localizedAuthFeedback(BuildContext context, String message) {
  final translation = _authFeedbackTranslations[message];
  if (translation != null) {
    return context.localized(ru: translation.$1, uk: translation.$2);
  }
  return context.isUkrainian ? 'Помилка: $message' : message;
}

const _authFeedbackTranslations = <String, (String, String)>{
  'Введите корректную почту': (
    'Введите корректную почту',
    'Введіть коректну електронну пошту',
  ),
  'Введите корректную почту.': (
    'Введите корректную почту.',
    'Введіть коректну електронну пошту.',
  ),
  'Пароль должен содержать минимум 8 символов': (
    'Пароль должен содержать минимум 8 символов',
    'Пароль має містити щонайменше 8 символів',
  ),
  'Проверьте почту и подтвердите регистрацию.': (
    'Проверьте почту и подтвердите регистрацию.',
    'Перевірте пошту та підтвердьте реєстрацію.',
  ),
  'Подтвердите почту. Мы повторно отправили письмо со ссылкой.': (
    'Подтвердите почту. Мы повторно отправили письмо со ссылкой.',
    'Підтвердьте пошту. Ми повторно надіслали лист із посиланням.',
  ),
  'Неверная почта или пароль.': (
    'Неверная почта или пароль.',
    'Неправильна електронна пошта або пароль.',
  ),
  'Аккаунт с этой почтой уже существует.': (
    'Аккаунт с этой почтой уже существует.',
    'Обліковий запис із цією поштою вже існує.',
  ),
  'Пароль слишком простой.': (
    'Пароль слишком простой.',
    'Пароль надто простий.',
  ),
  'Этот аккаунт отключён.': (
    'Этот аккаунт отключён.',
    'Цей обліковий запис вимкнено.',
  ),
  'Этот способ входа не включён в Firebase Authentication.': (
    'Этот способ входа не включён в Firebase Authentication.',
    'Цей спосіб входу не ввімкнено у Firebase Authentication.',
  ),
  'Вход через Google отменён.': (
    'Вход через Google отменён.',
    'Вхід через Google скасовано.',
  ),
  'Браузер заблокировал окно входа через Google.': (
    'Браузер заблокировал окно входа через Google.',
    'Браузер заблокував вікно входу через Google.',
  ),
  'Нет соединения с Firebase.': (
    'Нет соединения с Firebase.',
    'Немає з’єднання з Firebase.',
  ),
  'Аккаунт с этой почтой уже использует другой способ входа.': (
    'Аккаунт с этой почтой уже использует другой способ входа.',
    'Обліковий запис із цією поштою вже використовує інший спосіб входу.',
  ),
  'Google не вернул ID token. Проверьте OAuth client и SHA-1.': (
    'Google не вернул ID token. Проверьте OAuth client и SHA-1.',
    'Google не повернув ID token. Перевірте OAuth client і SHA-1.',
  ),
  'Google-вход недоступен в нативной Windows-версии. Используйте web/PWA или вход по почте.': (
    'Google-вход недоступен в нативной Windows-версии. Используйте web/PWA или вход по почте.',
    'Вхід через Google недоступний у нативній Windows-версії. Використовуйте web/PWA або вхід через пошту.',
  ),
  'Ошибка входа через Google.': (
    'Ошибка входа через Google.',
    'Помилка входу через Google.',
  ),
  'Firebase не вернул пользователя.': (
    'Firebase не вернул пользователя.',
    'Firebase не повернув користувача.',
  ),
  'Firebase не создал сессию.': (
    'Firebase не создал сессию.',
    'Firebase не створив сесію.',
  ),
  'Ошибка Firebase Authentication.': (
    'Ошибка Firebase Authentication.',
    'Помилка Firebase Authentication.',
  ),
};

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
            children: [
              const MarkoFadeUp(child: MarkoWordmark()),
              const SizedBox(height: 28),
              MarkoFadeUp(delay: const Duration(milliseconds: 80), child: form),
            ],
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
    final headline = context.localized(
      ru: 'Цены под\nконтролем.',
      uk: 'Ціни під\nконтролем.',
    );
    return Container(
      margin: const EdgeInsets.all(16),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(16),
        child: MarkoAtmosphere(
          variant: MarkoAtmosphereVariant.ink,
          beams: true,
          meteors: true,
          sparkles: true,
          child: Padding(
            padding: const EdgeInsets.all(48),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const MarkoWordmark(inverse: true),
                const Spacer(),
                MarkoFadeUp(
                  child: MarkoGradientText(
                    headline,
                    style: Theme.of(context).textTheme.displaySmall?.copyWith(
                      color: Colors.white,
                      fontSize: 42,
                    ),
                  ),
                ),
                const SizedBox(height: 18),
                MarkoFadeUp(
                  delay: const Duration(milliseconds: 90),
                  child: Text(
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
                ),
                const SizedBox(height: 32),
                MarkoFadeUp(
                  delay: const Duration(milliseconds: 160),
                  child: MarkoGlass(
                    child: Text.rich(
                      TextSpan(
                        children: [
                          const WidgetSpan(
                            alignment: PlaceholderAlignment.middle,
                            child: Icon(
                              Icons.bolt_rounded,
                              size: 16,
                              color: Colors.white,
                            ),
                          ),
                          TextSpan(
                            text: context.localized(
                              ru: '  Рабочее пространство мониторинга Prom',
                              uk: '  Робочий простір моніторингу Prom',
                            ),
                          ),
                        ],
                      ),
                      softWrap: true,
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
