# Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : The logo of the About tab, embedded so it travels with the HDA and the package
# Houdini : 21 and 22 (PySide6 only, no hou calls)
# Version : 1.0.0

import base64

# PNG, 188 x 200, the flower of the Karma Builder icon
LOGO_PNG_BASE64 = (
    "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"
)


# ------------------------------------------------------------
# The logo as a pixmap, or None when the picture cannot be read.
def logo_pixmap(height=None):
    from hutil.Qt import QtCore, QtGui
    pixmap = QtGui.QPixmap()
    if not pixmap.loadFromData(base64.b64decode("".join(LOGO_PNG_BASE64))):
        return None
    if height:
        pixmap = pixmap.scaledToHeight(int(height), QtCore.Qt.SmoothTransformation)
    return pixmap
