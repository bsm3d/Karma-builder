# BSM Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : Colors and style sheets
# Houdini : 21 and 22 (PySide6 only, no hou calls)
# Version : 1.0.0

from hutil.Qt import QtGui

_C = {
    "bg":          "#1e1e1e",
    "surface":     "#2b2b2b",
    "border":      "#3f3f3f",
    "text":        "#cccccc",
    "text_muted":  "#888888",
    "text_log":    "#a9b7c6",
    "accent_blue": "#2b4c7e",
    "accent_teal": "#325a70",
    "accent_green":"#2b4c3b",
    "accent_brown":"#4b3621",
    "danger":      "#7a3232",
    "primary":     "#3e5a78",
    "amber":       "#e8a317",
}


BSM_STYLE = f"""
/* Utilisation du thème natif de Houdini, on ne style que l'agencement et quelques éléments isolés. */
QTabBar::tab {{
    padding: 5px 12px;
}}
QGroupBox {{
    font-weight: bold;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 4px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}
QTextEdit {{
    background-color: {_C['surface']};
    color: {_C['text_log']};
    font-family: monospace;
}}
#hdriPreview, #snapshotPreview {{
    background-color: #1f1f1f;
    border: 1px solid #3f3f3f;
}}
"""


# ------------------------------------------------------------
# A full rule with a border: with only a background-color, the Houdini 22 theme draws no button, just the text.
# Padding kept small so the colored buttons stay the size of the standard ones.
def _btn_style(bg):
    base = QtGui.QColor(bg)
    luma = 0.299 * base.red() + 0.587 * base.green() + 0.114 * base.blue()
    fg = "#1e1e1e" if luma > 150 else "white"   # dark text on a light fill such as amber
    return (
        "QPushButton {{ background-color: {bg}; color: {fg}; padding: 3px 8px;"
        " border: 1px solid {edge}; border-radius: 4px; }}"
        "QPushButton:hover {{ background-color: {hover}; }}"
        "QPushButton:pressed {{ background-color: {pressed}; }}"
        "QPushButton:disabled {{ background-color: #3a3a3a; color: #7a7a7a; border-color: #4a4a4a; }}"
    ).format(bg=bg, fg=fg, edge=base.lighter(160).name(), hover=base.lighter(125).name(), pressed=base.darker(125).name())


# ----------------------------------------
def _slider_stylesheet():
    return (
        "QSlider::groove:horizontal {height: 8px; border-radius: 4px; background: #1f2123;}"
        "QSlider::sub-page:horizontal {background: #c9821a; border-radius: 4px;}"
        "QSlider::handle:horizontal {width: 14px; margin: -4px 0; border-radius: 7px; background: #e8a317;}"
    )
