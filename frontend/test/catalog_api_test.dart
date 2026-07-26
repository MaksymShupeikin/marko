import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/features/catalog/catalog_api.dart';

void main() {
  test('loads the catalog and sends search plus store filters', () async {
    final api = CatalogApi(
      ApiClient(
        client: MockClient((request) async {
          expect(request.method, 'GET');
          expect(request.url.path, '/api/v1/catalog/products');
          expect(request.url.queryParameters['q'], '03-31 402 053');
          expect(request.url.queryParameters['store_id'], 'store-b');
          expect(request.url.queryParameters['limit'], '48');
          return http.Response.bytes(
            utf8.encode(jsonEncode(_pageJson())),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
        baseUrl: 'http://api.test',
      ),
    );

    final page = await api.listProducts(
      query: '03-31 402 053',
      storeIds: const ['store-b'],
    );

    expect(page.items, hasLength(1));
    expect(page.items.single.stores, hasLength(2));
    expect(page.items.single.listingCount, 3);
    expect(page.items.single.recommendedPrice, 700);
    expect(page.items.single.recommendationAction, 'RAISE');
    expect(page.duplicatesRemoved, 1);
    expect(page.stores.map((store) => store.name), ['Parts Avto', 'ПРОФПАРТС']);
  });

  test(
    'loads only competitor evidence for the selected catalog product',
    () async {
      final api = CatalogApi(
        ApiClient(
          client: MockClient((request) async {
            expect(request.method, 'GET');
            expect(request.url.path, '/api/v1/catalog/competitors');
            expect(request.url.queryParameters['sku'], '0331402053');
            expect(request.url.queryParameters['oe'], '6 1131 36 9611');
            expect(request.url.queryParameters['brand'], 'KEMP');
            return http.Response.bytes(
              utf8.encode(
                jsonEncode({
                  'recommendation_id': 'recommendation-id',
                  'compared_at': '2026-07-25T13:00:00Z',
                  'current_price': '720.00',
                  'fair_price': '690.00',
                  'recommended_price': '700.00',
                  'currency': 'UAH',
                  'reason_codes': <String>[],
                  'items': [
                    {
                      'observation_id': 'observation-id',
                      'seller_id': 'auto-partner',
                      'seller_name': 'Auto Partner',
                      'title': 'Реле стартера Bosch для Mercedes',
                      'url': 'https://prom.ua/ua/p-competitor.html',
                      'price': '680.00',
                      'currency': 'UAH',
                      'is_available': true,
                      'normalized_price': '690.00',
                      'tier': 'aftermarket_a',
                      'match_confidence': '0.96',
                      'observed_at': '2026-07-25T12:00:00Z',
                    },
                  ],
                }),
              ),
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }),
          baseUrl: 'http://api.test',
        ),
      );

      final comparison = await api.listCompetitors(
        sku: '0331402053',
        oe: '6 1131 36 9611',
        brand: 'KEMP',
      );

      expect(comparison.items, hasLength(1));
      expect(comparison.items.single.sellerName, 'Auto Partner');
      expect(comparison.items.single.price, 680);
      expect(comparison.items.single.normalizedPrice, 690);
    },
  );

  test(
    'starts bounded catalog discovery and parses discovery candidates',
    () async {
      final api = CatalogApi(
        ApiClient(
          client: MockClient((request) async {
            expect(request.method, 'POST');
            expect(request.url.path, '/api/v1/catalog/competitors/discover');
            final body = jsonDecode(request.body) as Map<String, dynamic>;
            expect(body['sku'], '7E5 827 505 A');
            expect(body['oe'], '7E5 827 505 A');
            expect(body['brand'], 'Volkswagen');
            expect(body['title'], 'VW Transporter T5 T6 замок');
            expect(body['current_price'], 1800);
            expect(body['currency'], 'UAH');
            return http.Response.bytes(
              utf8.encode(
                jsonEncode({
                  'recommendation_id': null,
                  'compared_at': null,
                  'current_price': null,
                  'fair_price': null,
                  'recommended_price': null,
                  'currency': null,
                  'reason_codes': <String>[],
                  'items': <dynamic>[],
                  'discovery_run_id': 'discovery-run',
                  'discovered_at': '2026-07-25T14:00:00Z',
                  'discovery_query': '7E5827505A',
                  'discovery_status': 'completed',
                  'prom_reported_total': 91,
                  'discovered_total': 1,
                  'discovery_retrieved_count': 29,
                  'discovery_persisted_count': 29,
                  'owned_excluded_count': 0,
                  'discovery_rejected_count': 0,
                  'comparable_count': 0,
                  'review_count': 1,
                  'skipped_count': 28,
                  'selection_histogram': {
                    'TIER_UNKNOWN (REVIEW)': 1,
                    'OEM_NOT_FOUND': 28,
                  },
                  'search_pages_fetched': 1,
                  'search_page_limit': 1,
                  'unfetched_count': 62,
                  'coverage_ratio': '0.318681',
                  'coverage_reason': 'SEARCH_PAGE_LIMIT',
                  'selection_method_version':
                      'deterministic-candidate-gates-v1',
                  'selection_config_sha256': 'aaaaaaaa',
                  'brand_rules_dataset_id': 'NO_BRAND_DICTIONARY_CONFIGURED',
                  'discovery_items': [
                    {
                      'discovery_offer_id': 'discovery-offer',
                      'source_listing_id': '1402874053',
                      'seller_id': '668922',
                      'seller_name': 'Autoparts IF',
                      'title': 'Замок багажника 7E5827505A',
                      'url': 'https://prom.ua/ua/p1402874053-item.html',
                      'sku': 'DF-11260',
                      'brand': 'Detali IF',
                      'sale_price': '629.00',
                      'reference_price': null,
                      'currency': 'UAH',
                      'measure_unit': 'шт.',
                      'is_available': true,
                      'title_contains_query': true,
                      'identity_status': 'QUERY_TOKEN_PRESENT',
                      'source_confidence': '1.0000',
                      'reason_codes': ['DISCOVERY_ONLY_NOT_PRICING_EVIDENCE'],
                      'selection_status': 'REVIEW',
                      'selection_reason': 'TIER_UNKNOWN',
                      'passed_gates': [
                        'own_seller',
                        'dismantler_seller',
                        'condition',
                        'remanufactured',
                        'oem_identity',
                        'oem_stuffing',
                        'variant',
                        'package',
                        'applicability',
                      ],
                      'selection_flags': ['SAME_PLATFORM'],
                      'selection_details': {'stopped_gate': 'tier'},
                      'predicted_tier': 'unknown',
                      'tier_confidence': '0',
                    },
                  ],
                }),
              ),
              201,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }),
          baseUrl: 'http://api.test',
        ),
      );

      final comparison = await api.discoverCompetitors(
        sku: '7E5 827 505 A',
        oe: '7E5 827 505 A',
        brand: 'Volkswagen',
        title: 'VW Transporter T5 T6 замок',
        currentPrice: 1800,
        currency: 'UAH',
      );

      expect(comparison.hasComparison, isFalse);
      expect(comparison.hasDiscovery, isTrue);
      expect(comparison.promReportedTotal, 91);
      expect(comparison.discoveryItems.single.sellerName, 'Autoparts IF');
      expect(comparison.discoveryItems.single.salePrice, 629);
      expect(comparison.reviewCount, 1);
      expect(comparison.unfetchedCount, 62);
      expect(comparison.discoveryItems.single.selectionReason, 'TIER_UNKNOWN');
      expect(comparison.discoveryItems.single.passedGates, hasLength(9));
    },
  );
}

Map<String, dynamic> _pageJson() => {
  'items': [
    {
      'id': 'product-id',
      'identity_kind': 'brand_sku',
      'name': 'Втягивающее реле стартера Mercedes',
      'sku': '0331402053',
      'oe': null,
      'model_id': null,
      'brand': 'KEMP',
      'image_url': 'https://images.prom.ua/product.jpg',
      'price_min': '420.00',
      'price_max': '450.00',
      'currency': 'UAH',
      'listing_count': 3,
      'recommended_price': '700.00',
      'recommendation_currency': 'UAH',
      'recommendation_action': 'RAISE',
      'recommendation_computed_at': '2026-07-25T13:00:00Z',
      'stores': [
        _storeJson('store-a', '3912822', 'parts-avto', 2, '420.00'),
        _storeJson('store-b', '3325174', 'profparts', 1, '450.00'),
      ],
    },
  ],
  'total': 1,
  'catalog_total': 2,
  'listing_total': 3,
  'duplicates_removed': 1,
  'store_total': 2,
  'stores': [
    {'store_id': 'store-a', 'external_id': '3912822', 'name': 'Parts Avto'},
    {'store_id': 'store-b', 'external_id': '3325174', 'name': 'ПРОФПАРТС'},
  ],
  'limit': 48,
  'offset': 0,
};

Map<String, dynamic> _storeJson(
  String id,
  String externalId,
  String name,
  int listingCount,
  String price,
) => {
  'store_id': id,
  'external_id': externalId,
  'name': name,
  'url': 'https://prom.ua/ua/c$externalId-$name.html',
  'listing_url': 'https://prom.ua/ua/p1-product.html',
  'listing_count': listingCount,
  'price': price,
  'currency': 'UAH',
  'is_available': true,
};
