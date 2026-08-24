import 'dart:convert';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:heroicons/heroicons.dart';

import '../app_theme.dart';

String markoImageCacheKey(String url) {
  return sha256.convert(utf8.encode(url.trim())).toString();
}

CachedNetworkImageProvider markoImageProvider(String url) {
  final normalized = url.trim();
  return CachedNetworkImageProvider(
    normalized,
    cacheKey: markoImageCacheKey(normalized),
    maxWidth: 900,
  );
}

Future<void> precacheMarkoImages(
  BuildContext context,
  Iterable<String?> urls, {
  int limit = 12,
}) async {
  final uniqueUrls = urls
      .whereType<String>()
      .map((url) => url.trim())
      .where(_isHttpUrl)
      .toSet()
      .take(limit);

  await Future.wait(
    uniqueUrls.map(
      (url) =>
          precacheImage(markoImageProvider(url), context, onError: (_, _) {}),
    ),
  );
}

class MarkoCachedImage extends StatelessWidget {
  const MarkoCachedImage({
    required this.imageUrl,
    this.fit = BoxFit.cover,
    this.alignment = Alignment.center,
    super.key,
  });

  final String? imageUrl;
  final BoxFit fit;
  final Alignment alignment;

  @override
  Widget build(BuildContext context) {
    final url = imageUrl?.trim();
    if (url != null && url.startsWith('assets/')) {
      return Image.asset(
        url,
        width: double.infinity,
        height: double.infinity,
        fit: fit,
        alignment: alignment,
        errorBuilder: (_, _, _) => const _ImageFallback(),
      );
    }
    if (url == null || !_isHttpUrl(url)) return const _ImageFallback();

    return CachedNetworkImage(
      imageUrl: url,
      cacheKey: markoImageCacheKey(url),
      width: double.infinity,
      height: double.infinity,
      fit: fit,
      alignment: alignment,
      memCacheWidth: 900,
      maxWidthDiskCache: 900,
      fadeInDuration: const Duration(milliseconds: 180),
      fadeOutDuration: const Duration(milliseconds: 120),
      placeholder: (_, _) => const MarkoImageShimmer(),
      errorWidget: (_, _, _) => const _ImageFallback(),
    );
  }
}

class MarkoImageShimmer extends StatefulWidget {
  const MarkoImageShimmer({super.key});

  @override
  State<MarkoImageShimmer> createState() => _MarkoImageShimmerState();
}

class _MarkoImageShimmerState extends State<MarkoImageShimmer>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1150),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final highlight = Color.lerp(colors.surfaceMuted, colors.surface, 0.78)!;
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, _) {
        final position = -1.8 + (_controller.value * 3.6);
        return ShaderMask(
          blendMode: BlendMode.srcATop,
          shaderCallback: (bounds) => LinearGradient(
            begin: Alignment(position - 0.8, -0.3),
            end: Alignment(position + 0.8, 0.3),
            colors: [colors.surfaceMuted, highlight, colors.surfaceMuted],
            stops: const [0.25, 0.5, 0.75],
          ).createShader(bounds),
          child: ColoredBox(color: colors.surfaceMuted),
        );
      },
    );
  }
}

class _ImageFallback extends StatelessWidget {
  const _ImageFallback();

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return ColoredBox(
      color: colors.surfaceMuted,
      child: Center(
        child: HeroIcon(HeroIcons.photo, color: colors.muted, size: 30),
      ),
    );
  }
}

bool _isHttpUrl(String value) {
  final uri = Uri.tryParse(value);
  return uri != null &&
      (uri.scheme == 'https' || uri.scheme == 'http') &&
      uri.host.isNotEmpty;
}
