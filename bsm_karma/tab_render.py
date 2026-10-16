# BSM Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : Render tab: denoiser, filter and ray limits
# Houdini : 21 and 22 (PySide6 only, no hou calls)
# Version : 1.0.0

from hutil.Qt import QtWidgets
from .gauges import FloatSlider, IntSlider
from .widgets import wrap_tab

# ------------------------------------------------------------
class RenderTab:

    def _build_render_tab(self, tabs):
        tab_filters = QtWidgets.QWidget()
        form_filters = QtWidgets.QFormLayout(tab_filters)
        
        self.combo_denoiser = QtWidgets.QComboBox()
        self.combo_denoiser.addItems(["None", "Optix (GPU)", "OIDN (CPU)"])
        self.combo_denoiser.setCurrentText("Optix (GPU)")
        form_filters.addRow("Image Denoiser:", self.combo_denoiser)
        
        self.combo_pixel_filter = QtWidgets.QComboBox()
        self.combo_pixel_filter.addItems(["gauss", "box", "blackman", "blackmanharris"])
        self.combo_pixel_filter.setCurrentText("gauss")
        form_filters.addRow("Pixel Filter (AA):", self.combo_pixel_filter)

        self.sld_diffuse_limit = IntSlider(0, 16, 3)
        form_filters.addRow("Diffuse Limit:", self.sld_diffuse_limit)

        self.sld_reflection_limit = IntSlider(0, 16, 3)
        form_filters.addRow("Reflection Limit:", self.sld_reflection_limit)

        self.sld_transmission_limit = IntSlider(0, 16, 4)
        form_filters.addRow("Transmission Limit:", self.sld_transmission_limit)

        self.sld_vol_limit = IntSlider(0, 32, 8)
        form_filters.addRow("Volume Limit:", self.sld_vol_limit)

        self.sld_color_limit = FloatSlider(0.0, 100.0, 10.0)
        form_filters.addRow("Color Limit (Clamp):", self.sld_color_limit)

        self.sld_noise_level = FloatSlider(0.0, 1.0, 0.01)
        form_filters.addRow("Noise Level (Variance):", self.sld_noise_level)
        
        tabs.addTab(wrap_tab(tab_filters), "Render")
        self._config_tabs.append(tab_filters)
