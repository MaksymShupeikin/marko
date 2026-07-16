import 'dart:async';
import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../pricing/pricing_api.dart';
import '../pricing/pricing_controller.dart';
import '../pricing/pricing_models.dart';
import 'catalog_api.dart';
import 'catalog_models.dart';

class CatalogState {
  const CatalogState({
    required this.imports,
    this.isUploading = false,
    this.activeRun,
    this.error,
  });

  final List<CatalogImport> imports;
  final bool isUploading;
  final PricingRunSummary? activeRun;
  final String? error;

  CatalogState copyWith({
    List<CatalogImport>? imports,
    bool? isUploading,
    PricingRunSummary? activeRun,
    String? error,
    bool clearRun = false,
    bool clearError = false,
  }) {
    return CatalogState(
      imports: imports ?? this.imports,
      isUploading: isUploading ?? this.isUploading,
      activeRun: clearRun ? null : activeRun ?? this.activeRun,
      error: clearError ? null : error ?? this.error,
    );
  }
}

class CatalogController extends AsyncNotifier<CatalogState> {
  int _pollGeneration = 0;
  CatalogState get _current => state.value ?? const CatalogState(imports: []);

  @override
  Future<CatalogState> build() async {
    ref.onDispose(() => _pollGeneration++);
    final page = await ref.watch(catalogApiProvider).listImports();
    return CatalogState(imports: page.items);
  }

  Future<void> upload(String filename, Uint8List bytes) async {
    if (bytes.length > 25 * 1024 * 1024) {
      state = AsyncData(_current.copyWith(error: 'Файл больше 25 MB'));
      return;
    }
    state = AsyncData(_current.copyWith(isUploading: true, clearError: true));
    try {
      final imported = await ref
          .read(catalogApiProvider)
          .upload(filename: filename, bytes: bytes);
      state = AsyncData(
        _current.copyWith(
          imports: [
            imported,
            ..._current.imports.where((item) => item.id != imported.id),
          ],
          isUploading: false,
          clearError: true,
        ),
      );
    } catch (error) {
      state = AsyncData(
        _current.copyWith(isUploading: false, error: error.toString()),
      );
    }
  }

  Future<void> startRun(CatalogImport imported) async {
    if (!imported.canRun || _current.activeRun?.isFinished == false) return;
    try {
      final run = await ref.read(pricingApiProvider).startRun(imported.id);
      state = AsyncData(_current.copyWith(activeRun: run, clearError: true));
      final generation = ++_pollGeneration;
      unawaited(_followRun(run, generation));
    } catch (error) {
      state = AsyncData(_current.copyWith(error: error.toString()));
    }
  }

  Future<void> _followRun(PricingRunSummary run, int generation) async {
    var currentRun = run;
    while (generation == _pollGeneration && !currentRun.isFinished) {
      await Future<void>.delayed(const Duration(seconds: 2));
      try {
        currentRun = await ref.read(pricingApiProvider).getRun(run.id);
        if (generation != _pollGeneration) return;
        state = AsyncData(
          _current.copyWith(activeRun: currentRun, clearError: true),
        );
      } catch (error) {
        state = AsyncData(_current.copyWith(error: error.toString()));
      }
    }
    if (currentRun.isFinished) {
      ref.invalidate(recommendationsControllerProvider);
    }
  }
}

final catalogControllerProvider =
    AsyncNotifierProvider<CatalogController, CatalogState>(
      CatalogController.new,
    );
