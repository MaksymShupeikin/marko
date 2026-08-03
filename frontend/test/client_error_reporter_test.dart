import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/client_error_reporter.dart';

void main() {
  test(
    'client error telemetry hashes messages and strips filesystem paths',
    () async {
      final sent = <Map<String, dynamic>>[];
      final reporter =
          ClientErrorReporter(
              release: 'test-release',
              now: () => DateTime.utc(2026, 7, 30, 12),
              initialTransport: (event) async => sent.add(event),
            )
            ..updateRoute('/pricing/recommendations')
            ..updateCorrelationId('request-123');

      await reporter.capture(
        ArgumentError(
          'cost=1234.56 user@example.test /Users/private/catalog.xlsx',
        ),
        StackTrace.fromString(
          '#0 /Users/private/project/lib/secret.dart:42:7\n'
          '#1 package:marko_client/main.dart:10:3',
        ),
        kind: ClientErrorKind.zone,
      );

      expect(sent, hasLength(1));
      final encoded = jsonEncode(sent.single);
      expect(encoded, isNot(contains('1234.56')));
      expect(encoded, isNot(contains('user@example.test')));
      expect(encoded, isNot(contains('/Users/private')));
      expect(sent.single['exception_type'], 'ArgumentError');
      expect(
        sent.single['message_fingerprint'],
        matches(RegExp(r'^[0-9a-f]{64}$')),
      );
      expect(sent.single['stack_frames'], [
        'secret.dart:42:7',
        'main.dart:10:3',
      ]);
      expect(sent.single['route'], '/pricing/recommendations');
      expect(sent.single['correlation_id'], 'request-123');
    },
  );

  test('failed transport retains a bounded offline buffer for retry', () async {
    var attempts = 0;
    final sent = <Map<String, dynamic>>[];
    final reporter = ClientErrorReporter(
      release: 'test-release',
      maxBufferedEvents: 2,
      initialTransport: (_) async {
        attempts += 1;
        throw StateError('offline');
      },
    );

    await reporter.capture(StateError('one'), StackTrace.current);
    await reporter.capture(StateError('two'), StackTrace.current);
    await reporter.capture(StateError('three'), StackTrace.current);
    expect(reporter.bufferedEventCount, 2);

    reporter.attachTransport((event) async => sent.add(event));
    await reporter.flush();

    expect(attempts, greaterThanOrEqualTo(3));
    expect(sent, hasLength(2));
    expect(reporter.bufferedEventCount, 0);
  });
}
