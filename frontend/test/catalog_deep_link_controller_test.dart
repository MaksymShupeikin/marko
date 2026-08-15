import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/features/catalog/catalog_api.dart';
import 'package:marko_client/features/catalog/catalog_controller.dart';
import 'package:marko_client/features/catalog/catalog_models.dart';

void main() {
  test('deep link pins a catalog product outside the first page', () async {
    final api = _DeepLinkCatalogApi();
    final container = ProviderContainer(
      overrides: [catalogApiProvider.overrideWithValue(api)],
    );
    addTearDown(container.dispose);

    await container.read(catalogControllerProvider.future);
    final product = await container
        .read(catalogControllerProvider.notifier)
        .ensureVisible('deep-product');
    final state = container.read(catalogControllerProvider).requireValue;

    expect(product?.id, 'deep-product');
    expect(state.page.items.first.id, 'deep-product');
    expect(state.deepLinkUnavailable, isFalse);
    expect(api.requestedProductIds, ['deep-product']);
  });
}

class _DeepLinkCatalogApi extends CatalogApi {
  _DeepLinkCatalogApi()
    : super(
        ApiClient(
          client: MockClient((_) async => throw UnimplementedError()),
          baseUrl: 'http://api.test',
        ),
      );

  final List<String> requestedProductIds = [];

  @override
  Future<CatalogProductPage> listProducts({
    String query = '',
    List<String>? storeIds,
    int offset = 0,
    int limit = 48,
    String? kempStatus,
    bool noOem = false,
  }) async {
    return const CatalogProductPage(
      items: [],
      total: 10,
      catalogTotal: 10,
      listingTotal: 10,
      duplicatesRemoved: 0,
      storeTotal: 1,
      stores: [],
    );
  }

  @override
  Future<CatalogProduct> getProduct(String productId) async {
    requestedProductIds.add(productId);
    return CatalogProduct(
      id: productId,
      identityKind: 'brand_sku',
      name: 'Deep product',
      sku: 'SKU-1',
      oe: null,
      modelId: null,
      brand: 'KEMP',
      imageUrl: null,
      priceMin: 100,
      priceMax: 100,
      currency: 'UAH',
      listingCount: 1,
      stores: const [],
    );
  }
}
