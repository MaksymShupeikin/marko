import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

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
  static const _preferenceKey = 'marko.app_language';
  int _selectionRevision = 0;

  @override
  AppLanguage build() {
    unawaited(_restore(_selectionRevision));
    return AppLanguage.russian;
  }

  void select(AppLanguage language) {
    if (state == language) return;
    _selectionRevision += 1;
    state = language;
    unawaited(_persist(language));
  }

  Future<void> _restore(int expectedRevision) async {
    try {
      final preferences = await SharedPreferences.getInstance();
      final stored = preferences.getString(_preferenceKey);
      AppLanguage? language;
      for (final candidate in AppLanguage.values) {
        if (candidate.name == stored) {
          language = candidate;
          break;
        }
      }
      if (language != null &&
          ref.mounted &&
          expectedRevision == _selectionRevision) {
        state = language;
      }
    } catch (_) {
      // Persistence is optional: the language selector must still work when
      // platform storage is unavailable.
    }
  }

  Future<void> _persist(AppLanguage language) async {
    try {
      final preferences = await SharedPreferences.getInstance();
      await preferences.setString(_preferenceKey, language.name);
    } catch (_) {
      // Keep the in-memory selection even if platform storage is unavailable.
    }
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
