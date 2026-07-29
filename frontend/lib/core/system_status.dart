import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api_client.dart';

enum SystemHealth { active, collectionLimited }

final systemStatusProvider = FutureProvider.autoDispose<SystemHealth>((
  ref,
) async {
  final refreshTimer = Timer(const Duration(seconds: 30), ref.invalidateSelf);
  ref.onDispose(refreshTimer.cancel);
  final client = ref.watch(apiClientProvider);
  final responses = await Future.wait<dynamic>([
    client.getJson('/api/v1/health/ready', authenticated: false),
    client.getJson('/api/v1/health/source-access', authenticated: false),
  ]);
  final ready = Map<String, dynamic>.from(responses[0] as Map);
  final source = Map<String, dynamic>.from(responses[1] as Map);
  if (ready['status'] != 'ok') {
    throw const ApiException('Readiness probe did not return ok');
  }
  return source['live_collection_allowed'] == true
      ? SystemHealth.active
      : SystemHealth.collectionLimited;
}, retry: (_, _) => null);
