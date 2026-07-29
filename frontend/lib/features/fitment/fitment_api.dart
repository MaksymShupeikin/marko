import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import 'fitment_models.dart';

class FitmentApi {
  const FitmentApi(this._client);

  final ApiClient _client;

  Future<FitmentCandidatePage> listCandidates(String catalogItemId) async {
    final payload = await _client.getJson(
      '/api/v1/fitment/products/$catalogItemId/candidates',
      queryParameters: const {'limit': '250'},
    );
    return FitmentCandidatePage.fromJson(payload as Map<String, dynamic>);
  }

  Future<void> reviewCandidate(
    String assessmentId, {
    required String decision,
    required String reasonCode,
    String? comment,
    Map<String, String> evidenceVerdicts = const {},
  }) async {
    final sortedEvidence = evidenceVerdicts.entries.toList()
      ..sort((left, right) => left.key.compareTo(right.key));
    final evidencePayload = sortedEvidence
        .map(
          (entry) => {'evidence_claim_id': entry.key, 'verdict': entry.value},
        )
        .toList(growable: false);
    final normalizedComment = comment?.trim();
    final idempotencyKey = _idempotencyKey('fitment-candidate-review', {
      'assessment_id': assessmentId,
      'decision': decision,
      'reason_code': reasonCode,
      'comment': normalizedComment ?? '',
      'evidence_verdicts': evidencePayload,
    });
    await _client.postJson(
      '/api/v1/fitment/candidates/$assessmentId/review',
      body: {
        'idempotency_key': idempotencyKey,
        'decision': decision,
        'reason_code': reasonCode,
        if (normalizedComment != null && normalizedComment.isNotEmpty)
          'comment': normalizedComment,
        'evidence_verdicts': evidencePayload,
      },
    );
  }

  Future<FitmentMarketRecommendation?> getRecommendation(
    String catalogItemId,
  ) async {
    try {
      final payload = await _client.getJson(
        '/api/v1/fitment/products/$catalogItemId/recommendation',
      );
      return FitmentMarketRecommendation.fromJson(
        Map<String, dynamic>.from(payload as Map),
      );
    } on ApiException catch (error) {
      if (error.statusCode == 404) return null;
      rethrow;
    }
  }

  Future<FitmentMarketRecommendation> generateRecommendation(
    String catalogItemId, {
    required String analysisId,
    String strategy = 'balanced',
  }) async {
    final payload = await _client.postJson(
      '/api/v1/fitment/products/$catalogItemId/recommendations',
      body: {
        'idempotency_key': _idempotencyKey('fitment-recommendation-generate', {
          'catalog_item_id': catalogItemId,
          'analysis_id': analysisId,
          'strategy': strategy,
        }),
        'analysis_id': analysisId,
        'strategy': strategy,
      },
    );
    return FitmentMarketRecommendation.fromJson(
      Map<String, dynamic>.from(payload as Map),
    );
  }

  Future<void> reviewRecommendation(
    String recommendationId, {
    required String operation,
    required String reasonCode,
    double? approvedPrice,
    String? comment,
    bool allowBelowFloor = false,
    bool belowFloorWarningConfirmed = false,
  }) async {
    if (!{'accept', 'reject', 'defer', 'research'}.contains(operation)) {
      throw ArgumentError.value(operation, 'operation');
    }
    await _client.postJson(
      '/api/v1/fitment/recommendations/$recommendationId/$operation',
      body: {
        'idempotency_key': _idempotencyKey('fitment-recommendation-review', {
          'recommendation_id': recommendationId,
          'operation': operation,
          'approved_price': approvedPrice?.toString() ?? '',
          'reason_code': reasonCode,
          'comment': comment?.trim() ?? '',
          'allow_below_floor': allowBelowFloor,
          'below_floor_warning_confirmed': belowFloorWarningConfirmed,
        }),
        'approved_price': ?approvedPrice,
        'reason_code': reasonCode,
        if (comment != null && comment.trim().isNotEmpty)
          'comment': comment.trim(),
        'accept_with_modification':
            operation == 'accept' && approvedPrice != null,
        'allow_below_floor': allowBelowFloor,
        'below_floor_warning_confirmed': belowFloorWarningConfirmed,
      },
    );
  }

  Future<void> markSellerRelation(
    FitmentCandidate candidate, {
    required String relation,
    required String reason,
  }) async {
    if (!{'own', 'related'}.contains(relation)) {
      throw ArgumentError.value(relation, 'relation');
    }
    await _client.postJson(
      '/api/v1/fitment/sellers/${Uri.encodeComponent(candidate.sellerId)}/mark-$relation',
      body: {
        'idempotency_key': _idempotencyKey('fitment-seller-relation', {
          'seller_id': candidate.sellerId,
          'relation': relation,
          'reason': reason.trim(),
          'observation_id': candidate.observationId,
          'assessment_id': candidate.id,
        }),
        'seller_name': candidate.sellerName,
        'confidence': relation == 'own' ? 1 : 0.9,
        'evidence': [
          {
            'type': 'human_operator_decision',
            'observation_id': candidate.observationId,
            'assessment_id': candidate.id,
          },
        ],
        'reason': reason,
      },
    );
  }

  String _idempotencyKey(String scope, Map<String, dynamic> content) {
    final canonical = jsonEncode({
      'scope': scope,
      'content': _canonicalize(content),
    });
    return sha256.convert(utf8.encode(canonical)).toString();
  }

  dynamic _canonicalize(dynamic value) {
    if (value is Map) {
      final entries =
          value.entries
              .map((entry) => MapEntry(entry.key.toString(), entry.value))
              .toList()
            ..sort((left, right) => left.key.compareTo(right.key));
      return <String, dynamic>{
        for (final entry in entries) entry.key: _canonicalize(entry.value),
      };
    }
    if (value is Iterable) {
      return value.map(_canonicalize).toList(growable: false);
    }
    return value;
  }
}

final fitmentApiProvider = Provider<FitmentApi>((ref) {
  return FitmentApi(ref.watch(apiClientProvider));
});
