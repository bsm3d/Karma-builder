# previews.py - BSM Karma Builder - sun compass, sun altitude and atmosphere drawings
# Version : 2026.10.15.1 | Revision : 15-10-2026 | Auteur : BSM

import math
from hutil.Qt import QtWidgets, QtCore, QtGui

# ------------------------------------------------------------
class SunCompassWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.azimuth = 0.0
        self.elevation = 30.0
        self.setFixedSize(140, 140)
        self.setStyleSheet("background-color: #2b2b2b; border: 1px solid #1a1a1a; border-radius: 4px;")
        


    # ------------------------------------------------------------------------
    def set_azimuth(self, degrees):
        self.azimuth = float(degrees) % 360.0
        self.update()
        

    # ----------------------------------------------------------------
    def set_elevation(self, degrees):
        self.elevation = float(degrees)
        self.update()
        

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        
        center_x, center_y = 70, 70
        radius = 55
        
        painter.setPen(QtGui.QPen(QtGui.QColor(100, 100, 100), 1))
        painter.setBrush(QtGui.QColor(40, 40, 40))
        painter.drawEllipse(center_x - radius, center_y - radius, radius * 2, radius * 2)
        
        painter.setPen(QtGui.QPen(QtGui.QColor(200, 200, 200)))
        font = QtGui.QFont("Segoe UI", 8, QtGui.QFont.Bold)
        painter.setFont(font)
        
        painter.drawText(center_x - 10, center_y - radius + 4, 20, 16, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop, "N")
        painter.drawText(center_x - 10, center_y + radius - 20, 20, 16, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom, "S")
        painter.drawText(center_x + radius - 24, center_y - 8, 20, 16, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, "E")
        painter.drawText(center_x - radius + 4, center_y - 8, 20, 16, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, "W")
        
        painter.setPen(QtGui.QPen(QtGui.QColor(80, 80, 80), 1))
        painter.drawLine(center_x, center_y - radius, center_x, center_y + radius)
        painter.drawLine(center_x - radius, center_y, center_x + radius, center_y)
        
        # angle goes clockwise from top (N = 0)
        sun_rad = math.radians(self.azimuth - 90)
        # altitude maps from 90 (center) to 0 (edge) to -20 (slightly outside or hidden)
        alt_clamped = max(-20.0, min(90.0, self.elevation))
        mapped_r = radius * (1.0 - (alt_clamped / 90.0)) if alt_clamped >= 0 else radius + (radius * 0.1)
        
        sun_x = center_x + mapped_r * math.cos(sun_rad)
        sun_y = center_y + mapped_r * math.sin(sun_rad)
        
        color = QtGui.QColor(255, 200, 0) if alt_clamped > 0 else QtGui.QColor(255, 100, 0, 100)
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 1))
        painter.setBrush(color)
        painter.drawEllipse(int(sun_x - 5), int(sun_y - 5), 10, 10)
        painter.end()


class SunAltitudeWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.elevation = 30.0
        self.setFixedSize(140, 140)
        self.setStyleSheet("background-color: #2b2b2b; border: 1px solid #1a1a1a; border-radius: 4px;")
        

    # ----------------------------------------
    def set_elevation(self, degrees):
        self.elevation = float(degrees)
        self.update()
        

    # ----------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        
        center_x, center_y = 30, 110
        radius = 80
        
        painter.setPen(QtGui.QPen(QtGui.QColor(100, 100, 100), 1))
        painter.setBrush(QtGui.QColor(50, 50, 50))
        # drawPie angles are in 1/16 of a degree
        painter.drawPie(center_x - radius, center_y - radius, radius * 2, radius * 2, 0, 90 * 16)
        
        painter.setPen(QtGui.QPen(QtGui.QColor(120, 120, 120), 2))
        painter.drawLine(center_x - 10, center_y, center_x + radius + 10, center_y)
        painter.drawLine(center_x, center_y + 10, center_x, center_y - radius - 10)
        
        painter.setPen(QtGui.QPen(QtGui.QColor(200, 200, 200)))
        font = QtGui.QFont("Segoe UI", 8, QtGui.QFont.Bold)
        painter.setFont(font)
        painter.drawText(center_x + radius + 5, center_y - 6, 25, 16, QtCore.Qt.AlignLeft, "0°")
        painter.drawText(center_x - 12, center_y - radius - 24, 25, 16, QtCore.Qt.AlignCenter, "90°")
        
        alt_clamped = max(-20.0, min(90.0, self.elevation))
        sun_rad = math.radians(alt_clamped)
        sun_x = center_x + radius * math.cos(sun_rad)
        sun_y = center_y - radius * math.sin(sun_rad)
        
        if alt_clamped >= 0:
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 0, 100), 1, QtCore.Qt.DashLine))
            painter.drawLine(center_x, center_y, int(sun_x), int(sun_y))
            
        color = QtGui.QColor(255, 200, 0) if alt_clamped > 0 else QtGui.QColor(255, 100, 0, 100)
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 1))
        painter.setBrush(color)
        painter.drawEllipse(int(sun_x - 5), int(sun_y - 5), 10, 10)
        
        painter.setPen(QtGui.QPen(QtGui.QColor(180, 180, 180)))
        painter.drawText(center_x + 10, center_y + 10, 100, 16, QtCore.Qt.AlignLeft, f"Alt: {self.elevation:.1f}°")
        painter.end()


# ------------------------------------------------------------
class AtmosphereVisualWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.fog_height = 30.0
        self.fog_density = 0.25
        self.cloud_alt = 140.0
        self.cloud_density = 0.20
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.setMinimumHeight(150)
        self.setStyleSheet("background-color: #2b2b2b; border: 1px solid #1a1a1a; border-radius: 4px;")
        

    def update_fog(self, height, density):
        self.fog_height = height
        self.fog_density = density
        self.update()
        

    # ------------------------------------------------------------
    def update_cloud(self, alt, density):
        self.cloud_alt = alt
        self.cloud_density = density
        self.update()

    # ------------------------------------------------------------
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        
        w = self.width()
        h = self.height()
        ground_y = h - 20
        
        def map_alt(alt):
            return (min(max(alt, 0), 13000.0) / 13000.0) ** 0.5
            
        grad = QtGui.QLinearGradient(0, 0, 0, ground_y)
        grad.setColorAt(0, QtGui.QColor(40, 60, 90))
        grad.setColorAt(1, QtGui.QColor(80, 100, 120))
        painter.fillRect(0, 0, w, ground_y, grad)
        
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(45, 45, 45))
        painter.drawRect(0, ground_y, w, 20)
        painter.setPen(QtGui.QPen(QtGui.QColor(120, 120, 120), 1))
        painter.drawLine(0, ground_y, w, ground_y)
        
        fog_pixels = int(map_alt(self.fog_height) * (ground_y - 20))
        
        fog_alpha = min(255, int(self.fog_density * 800))
        if fog_alpha > 0 and fog_pixels > 0:
            fog_grad = QtGui.QLinearGradient(0, ground_y - fog_pixels, 0, ground_y)
            fog_grad.setColorAt(0, QtGui.QColor(200, 200, 200, 0))
            fog_grad.setColorAt(1, QtGui.QColor(200, 200, 200, fog_alpha))
            painter.fillRect(0, ground_y - fog_pixels, w, fog_pixels, fog_grad)
            
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 255)))
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(5, ground_y - int(fog_pixels*0.5) - 5, w, 20, QtCore.Qt.AlignLeft, f"Fog: {self.fog_height:.0f}m")
            
        cloud_y = ground_y - int(map_alt(self.cloud_alt) * (ground_y - 20))
        cloud_alpha = min(255, int(self.cloud_density * 400))
        
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 150), 1, QtCore.Qt.DashLine))
        painter.drawLine(0, cloud_y, w, cloud_y)
        
        if cloud_alpha > 0:
            font.setPointSize(28)
            painter.setFont(font)
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, max(150, cloud_alpha))))
            for x in range(w // 2, w - 20, 80):
                painter.drawText(x, cloud_y + 15, "☁")
            
        font = painter.font()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        
        if self.cloud_alt < 2000:
            c_type = "Stratus / Cumulus"
        elif self.cloud_alt < 7000:
            c_type = "Altocumulus / Altostratus"
        else:
            c_type = "Cirrus / Cirrostratus"
            
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 255)))
        painter.drawText(5, cloud_y - 18, w, 20, QtCore.Qt.AlignLeft, f"Cloud: {self.cloud_alt:.0f}m ({c_type})")

        painter.end()
