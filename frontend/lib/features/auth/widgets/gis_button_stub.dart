import 'package:flutter/widgets.dart';

/// Off the web there is no GIS button — [GoogleAuthButton] never calls this.
Widget renderGisButton({required double width, required bool dark}) =>
    const SizedBox.shrink();
