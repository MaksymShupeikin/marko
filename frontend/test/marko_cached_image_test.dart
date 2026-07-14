import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/widgets/marko_cached_image.dart';

void main() {
  test('image cache key is a stable SHA-256 of the normalized URL', () {
    const url = 'https://images.prom.ua/product.jpg';

    final key = markoImageCacheKey(url);

    expect(key, hasLength(64));
    expect(markoImageCacheKey('  $url  '), key);
    expect(markoImageCacheKey('$url?v=2'), isNot(key));
    expect(markoImageProvider(url).cacheKey, key);
  });
}
