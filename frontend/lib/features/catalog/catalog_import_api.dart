import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import 'catalog_import_models.dart';

class CatalogImportApi {
  const CatalogImportApi(this._client);

  final ApiClient _client;

  Future<CatalogImportPreview> preview({
    required String filename,
    required Uint8List bytes,
  }) async {
    final payload = await _client.postMultipart(
      '/api/v1/catalog/imports/preview',
      filename: filename,
      bytes: bytes,
    );
    return CatalogImportPreview.fromJson(payload as Map<String, dynamic>);
  }

  Future<CatalogImportBatch> upload({
    required String filename,
    required Uint8List bytes,
    required String sheetName,
    required Map<String, String> mapping,
  }) async {
    final payload = await _client.postMultipart(
      '/api/v1/catalog/imports',
      filename: filename,
      bytes: bytes,
      fields: {'sheet_name': sheetName, 'mapping': jsonEncode(mapping)},
    );
    return CatalogImportBatch.fromJson(payload as Map<String, dynamic>);
  }

  Future<List<CatalogImportBatch>> list({int limit = 100}) async {
    final payload = await _client.getJson(
      '/api/v1/catalog/imports',
      queryParameters: {'limit': '$limit', 'offset': '0'},
    );
    return ((payload as Map<String, dynamic>)['items'] as List<dynamic>)
        .map(
          (item) => CatalogImportBatch.fromJson(item as Map<String, dynamic>),
        )
        .toList(growable: false);
  }
}

final catalogImportApiProvider = Provider<CatalogImportApi>((ref) {
  return CatalogImportApi(ref.watch(apiClientProvider));
});
