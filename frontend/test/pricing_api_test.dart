import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/features/pricing/pricing_api.dart';

void main() {
  test('requests recommendations in economic-priority order', () async {
    final api = PricingApi(
      ApiClient(
        client: MockClient((request) async {
          expect(request.url.path, '/api/v1/pricing/recommendations');
          expect(request.url.queryParameters['sort'], 'priority');
          expect(request.url.queryParameters['queue'], 'raise');
          expect(request.url.queryParameters['action'], 'RAISE');
          return http.Response(
            jsonEncode({
              'items': <dynamic>[],
              'total': 0,
              'run_id': null,
              'limit': 250,
              'offset': 0,
            }),
            200,
          );
        }),
        baseUrl: 'http://api.test',
      ),
    );

    final page = await api.listRecommendations(action: 'RAISE');

    expect(page.items, isEmpty);
    expect(page.total, 0);
  });

  test('records an explicit recommendation decision', () async {
    final api = PricingApi(
      ApiClient(
        client: MockClient((request) async {
          expect(
            request.url.path,
            '/api/v1/pricing/recommendations/rec-1/decisions',
          );
          expect(jsonDecode(request.body)['decision'], 'overridden');
          expect(jsonDecode(request.body)['new_price'], '750.00');
          return http.Response('{}', 201);
        }),
        baseUrl: 'http://api.test',
      ),
    );

    await api.recordDecision('rec-1', {
      'decision': 'overridden',
      'new_price': '750.00',
      'allow_below_cost': false,
      'reason': 'Manual target',
    });
  });

  test('requests the manual-review queue without mixing score units', () async {
    final api = PricingApi(
      ApiClient(
        client: MockClient((request) async {
          expect(request.url.queryParameters['queue'], 'review');
          expect(request.url.queryParameters['sort'], 'review_priority');
          return http.Response(
            jsonEncode({
              'items': <dynamic>[],
              'total': 0,
              'run_id': null,
              'limit': 250,
              'offset': 0,
            }),
            200,
          );
        }),
        baseUrl: 'http://api.test',
      ),
    );

    await api.listRecommendations(queue: 'review', sort: 'review_priority');
  });

  test('saves a tier override as a new classification', () async {
    final api = PricingApi(
      ApiClient(
        client: MockClient((request) async {
          expect(
            request.url.path,
            '/api/v1/pricing/observations/obs-1/tier-overrides',
          );
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['tier'], 'aftermarket_a');
          expect(body['reason'], 'Verified manufacturer catalogue');
          return http.Response('{}', 201);
        }),
        baseUrl: 'http://api.test',
      ),
    );

    await api.overrideTier(
      'obs-1',
      tier: 'aftermarket_a',
      reason: 'Verified manufacturer catalogue',
    );
  });

  test('verifies a recommendation through the replay endpoint', () async {
    final api = PricingApi(
      ApiClient(
        client: MockClient((request) async {
          expect(
            request.url.path,
            '/api/v1/pricing/recommendations/rec-1/replay',
          );
          return http.Response(
            jsonEncode({
              'recommendation_id': 'rec-1',
              'replay_contract_version': 'recommendation-replay-v1',
              'calculated_at': '2026-07-16T12:00:00Z',
              'exact_match': true,
              'mismatches': <String, dynamic>{},
              'replayed': {'action': 'RAISE'},
            }),
            200,
          );
        }),
        baseUrl: 'http://api.test',
      ),
    );

    final replay = await api.verifyReplay('rec-1');

    expect(replay.exactMatch, isTrue);
    expect(replay.contractVersion, 'recommendation-replay-v1');
    expect(replay.replayed['action'], 'RAISE');
  });
}
