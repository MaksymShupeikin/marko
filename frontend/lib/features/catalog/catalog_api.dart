import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import 'catalog_models.dart';

class CatalogApi {
  const CatalogApi(this._client);

  final ApiClient _client;

  Future<CatalogImportPage> listImports() async {
    final payload = await _client.getJson(
      '/api/v1/catalog/imports',
      queryParameters: {'limit': '100', 'offset': '0'},
    );
    return CatalogImportPage.fromJson(payload as Map<String, dynamic>);
  }

  Future<CatalogImport> upload({
    required String filename,
    required Uint8List bytes,
  }) async {
    final payload = await _client.postMultipart(
      '/api/v1/catalog/imports',
      filename: filename,
      bytes: bytes,
    );
    return CatalogImport.fromJson(payload as Map<String, dynamic>);
  }
}

final catalogApiProvider = Provider<CatalogApi>((ref) {
  return CatalogApi(ref.watch(apiClientProvider));
});
