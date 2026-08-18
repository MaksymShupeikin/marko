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

  /// Максимум, который принимает `/api/v1/catalog/items` за один запрос.
  static const int _itemPageSize = 250;

  /// Первые [limit] позиций импорта в порядке файла.
  ///
  /// Ограниченная область прогона описывается контрактом запуска только явным
  /// списком идентификаторов, поэтому «первые 300» приходится собрать здесь.
  /// Порядок задаёт сервер (`source_row`, затем `id`), так что выбор
  /// воспроизводим и объясним владельцу: это начало его же файла.
  Future<List<String>> listItemIds(String batchId, {required int limit}) async {
    final ids = <String>[];
    while (ids.length < limit) {
      final page = limit - ids.length < _itemPageSize
          ? limit - ids.length
          : _itemPageSize;
      final payload = await _client.getJson(
        '/api/v1/catalog/items',
        queryParameters: {
          'batch_id': batchId,
          'limit': '$page',
          'offset': '${ids.length}',
        },
        // Часть запуска ограниченной области: страницы собираются
        // последовательно, и на большом импорте их несколько. Общий
        // 15-секундный лимит обрывал сбор до того, как область была собрана.
        timeout: const Duration(minutes: 2),
      );
      final items = (payload as Map<String, dynamic>)['items'] as List<dynamic>;
      ids.addAll(
        items.map((item) => (item as Map<String, dynamic>)['id'] as String),
      );
      // Импорт кончился раньше запрошенной границы — это нормальный случай,
      // а не ошибка: предпросмотр посчитает то, что действительно есть.
      if (items.length < page) break;
    }
    return List<String>.unmodifiable(ids);
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
