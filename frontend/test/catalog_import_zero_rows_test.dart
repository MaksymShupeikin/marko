import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/catalog/catalog_import_dialog.dart';
import 'package:marko_client/features/catalog/catalog_import_models.dart';

/// The backend marks a batch `failed` when it could not parse a single row —
/// usually a wrong sheet or a mapping that points at empty columns. The dialog
/// treated everything that was not `partial` as a success, so an import that
/// stored nothing was announced as "Каталог импортирован" and the rest of the
/// app was told to reload a catalog that had not changed.
void main() {
  testWidgets('an import that accepted no rows is reported as a failure', (
    tester,
  ) async {
    var imported = 0;
    final client = MockClient((request) async {
      if (request.url.path.endsWith('/imports/preview')) {
        return _jsonResponse(_previewJson());
      }
      if (request.url.path.endsWith('/imports')) {
        return _jsonResponse(_failedImportJson());
      }
      return http.Response('not found', 404);
    });

    await tester.pumpWidget(
      _app(
        client: client,
        child: CatalogImportDialog(
          canAdministerWorkspace: true,
          onImported: () => imported += 1,
          pickFile: () async => PickedCatalogFile(
            name: 'catalog.xlsx',
            bytes: Uint8List.fromList([1, 2, 3]),
          ),
        ),
      ),
    );

    await tester.tap(find.byKey(const ValueKey('catalog-import-pick-file')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('catalog-import-sheet')));
    await tester.pumpAndSettle();
    await tester.tap(find.textContaining('Прайс').last);
    await tester.pumpAndSettle();
    await tester.ensureVisible(
      find.byKey(const ValueKey('catalog-import-submit')),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('catalog-import-submit')));
    await tester.pumpAndSettle();

    expect(
      imported,
      0,
      reason:
          'nothing was written, so no screen should reload as if the catalog '
          'had changed',
    );
    expect(
      find.text('Каталог импортирован'),
      findsNothing,
      reason: 'zero accepted rows is not a successful import',
    );
    expect(find.text('Каталог не импортирован'), findsOneWidget);
    expect(find.textContaining('Записано 0 из 120'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('catalog-import-close-success')),
      findsNothing,
    );
    expect(find.textContaining('EMPTY_REQUIRED_CELL'), findsWidgets);
    expect(tester.takeException(), isNull);
  });

  test('a failed batch is neither success nor partial', () {
    final batch = CatalogImportBatch.fromJson(_failedImportJson());
    expect(batch.isSuccess, isFalse);
    expect(batch.isPartial, isFalse);
  });
}

Widget _app({required http.Client client, required Widget child}) {
  return ProviderScope(
    overrides: [
      apiClientProvider.overrideWithValue(
        ApiClient(client: client, baseUrl: 'https://api.example.test'),
      ),
    ],
    child: MaterialApp(
      theme: AppTheme.light,
      locale: const Locale('ru'),
      supportedLocales: const [Locale('ru'), Locale('uk')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      home: Scaffold(body: Center(child: child)),
    ),
  );
}

http.Response _jsonResponse(Object payload, {int statusCode = 200}) {
  return http.Response(
    jsonEncode(payload),
    statusCode,
    headers: {'content-type': 'application/json'},
  );
}

Map<String, dynamic> _previewJson() => {
  'filename': 'catalog.xlsx',
  'content_size': 3,
  'max_size_bytes': 26214400,
  'requires_sheet_choice': true,
  'sheets': [
    {
      'name': 'Прайс',
      'row_count': 120,
      'headers': ['SKU', 'OE', 'Name', 'Category', 'Price'],
      'suggested_mapping': {
        'sku': 'SKU',
        'oe': 'OE',
        'name': 'Name',
        'category': 'Category',
        'price': 'Price',
      },
      'mapping_error': null,
      'sample_rows': <Object>[],
      'is_catalog_candidate': true,
    },
  ],
};

Map<String, dynamic> _failedImportJson() => {
  'id': 'batch-empty',
  'filename': 'catalog.xlsx',
  'status': 'failed',
  'column_mapping': {
    'sku': 'SKU',
    'oe': 'OE',
    'name': 'Name',
    'category': 'Category',
    'price': 'Price',
  },
  'total_rows': 120,
  'imported_rows': 0,
  'rejected_rows': 120,
  'error_log': [
    {
      'row': 2,
      'code': 'EMPTY_REQUIRED_CELL',
      'message': 'EMPTY_REQUIRED_CELL: price is empty',
    },
  ],
  'created_at': '2026-07-31T04:00:00Z',
};
