import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

enum AppLanguage {
  russian,
  ukrainian;

  Locale get locale => switch (this) {
    AppLanguage.russian => const Locale('ru'),
    AppLanguage.ukrainian => const Locale('uk'),
  };

  String get shortLabel => switch (this) {
    AppLanguage.russian => 'RU',
    AppLanguage.ukrainian => 'UA',
  };

  String get nativeLabel => switch (this) {
    AppLanguage.russian => 'Русский',
    AppLanguage.ukrainian => 'Українська',
  };
}

class AppLanguageController extends Notifier<AppLanguage> {
  @override
  AppLanguage build() => AppLanguage.russian;

  void select(AppLanguage language) {
    if (state != language) state = language;
  }
}

final appLanguageProvider =
    NotifierProvider<AppLanguageController, AppLanguage>(
      AppLanguageController.new,
    );

extension MarkoLocalization on BuildContext {
  bool get isUkrainian =>
      Localizations.maybeLocaleOf(this)?.languageCode == 'uk';

  String localized({required String ru, required String uk}) {
    return isUkrainian ? uk : ru;
  }
}
