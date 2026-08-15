import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

class AppThemeModeController extends Notifier<ThemeMode> {
  static const _preferenceKey = 'marko.app_theme_mode';
  int _revision = 0;

  @override
  ThemeMode build() {
    unawaited(_restore(_revision));
    return ThemeMode.light;
  }

  void select(ThemeMode mode) {
    if (state == mode) return;
    _revision += 1;
    state = mode;
    unawaited(_persist(mode));
  }

  void cycle() {
    select(switch (state) {
      ThemeMode.light => ThemeMode.dark,
      ThemeMode.dark => ThemeMode.system,
      ThemeMode.system => ThemeMode.light,
    });
  }

  Future<void> _restore(int expectedRevision) async {
    try {
      final preferences = await SharedPreferences.getInstance();
      final stored = preferences.getString(_preferenceKey);
      final mode = switch (stored) {
        'dark' => ThemeMode.dark,
        'system' => ThemeMode.system,
        'light' => ThemeMode.light,
        _ => null,
      };
      if (mode != null && ref.mounted && expectedRevision == _revision) {
        state = mode;
      }
    } catch (_) {}
  }

  Future<void> _persist(ThemeMode mode) async {
    try {
      final preferences = await SharedPreferences.getInstance();
      await preferences.setString(_preferenceKey, mode.name);
    } catch (_) {}
  }
}

final appThemeModeProvider =
    NotifierProvider<AppThemeModeController, ThemeMode>(
      AppThemeModeController.new,
    );
