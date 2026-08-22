import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/features/products/products_api.dart';

void main() {
  test(
    'uploads the catalog file as multipart and reports the result',
    () async {
      final api = ProductsApi(
        ApiClient(
          client: MockClient((request) async {
            expect(request.method, 'POST');
            expect(request.url.path, '/api/v1/stores/import-file');
            expect(
              request.headers['content-type'],
              contains('multipart/form-data'),
            );
            // The part carries the field name and the original file name.
            final body = String.fromCharCodes(request.bodyBytes);
            expect(body, contains('name="file"'));
            expect(body, contains('filename="export.xlsx"'));
            return http.Response(
              jsonEncode({
                'store_id': 'store-id',
                'store_name': 'kemp',
                'imported': 4901,
                'skipped': 0,
              }),
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }),
          baseUrl: 'http://api.test',
        ),
      );

      final result = await api.importCatalogFile('export.xlsx', [1, 2, 3, 4]);

      expect(result.storeName, 'kemp');
      expect(result.imported, 4901);
      expect(result.summary, 'Магазин «kemp»: завантажено 4901 товарів.');
    },
  );

  test('import summary mentions skipped rows when there are any', () {
    final api = ProductsApi(
      ApiClient(
        client: MockClient(
          (_) async => http.Response(
            jsonEncode({
              'store_id': 'store-id',
              'store_name': 'kemp',
              'imported': 10,
              'skipped': 2,
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          ),
        ),
        baseUrl: 'http://api.test',
      ),
    );

    expectLater(
      api.importCatalogFile('export.xlsx', [1]).then((r) => r.summary),
      completion('Магазин «kemp»: завантажено 10 товарів, пропущено 2.'),
    );
  });
}
