import 'package:flutter/widgets.dart';
import 'package:google_sign_in_web/web_only.dart' as gis;

/// Google Identity Services renders the button itself: the browser only hands
/// out an ID token for a click inside their own frame, so the styling we get
/// is whatever [gis.GSIButtonConfiguration] allows.
Widget renderGisButton({required double width, required bool dark}) {
  return gis.renderButton(
    configuration: gis.GSIButtonConfiguration(
      theme: dark ? gis.GSIButtonTheme.filledBlack : gis.GSIButtonTheme.outline,
      size: gis.GSIButtonSize.large,
      text: gis.GSIButtonText.continueWith,
      shape: gis.GSIButtonShape.rectangular,
      logoAlignment: gis.GSIButtonLogoAlignment.center,
      // GIS caps the button at 400px.
      minimumWidth: width.clamp(200, 400),
      locale: 'uk',
    ),
  );
}
