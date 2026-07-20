import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/features/stores/stores_controller.dart';

void main() {
  test('accepts canonical Prom seller URL', () {
    expect(
      isSupportedPromStoreUrl('https://prom.ua/ua/c2847093-kemp.html'),
      isTrue,
    );
  });

  test('accepts public Prom seller subdomain', () {
    expect(isSupportedPromStoreUrl('https://pilot-avto.prom.ua/ua/'), isTrue);
  });

  test('rejects non-HTTPS and lookalike hosts', () {
    expect(isSupportedPromStoreUrl('http://pilot-avto.prom.ua/ua/'), isFalse);
    expect(
      isSupportedPromStoreUrl('https://prom.ua.evil.example/store'),
      isFalse,
    );
  });
}
