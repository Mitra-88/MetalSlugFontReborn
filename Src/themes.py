from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette


def _disabled(palette, window, text):
    group = QPalette.Disabled
    palette.setColor(group, QPalette.Window, window)
    palette.setColor(group, QPalette.WindowText, text)
    palette.setColor(group, QPalette.Text, text)
    palette.setColor(group, QPalette.ButtonText, text)


def light_mode():
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(245, 245, 245))
    palette.setColor(QPalette.WindowText, QColor(0, 0, 0))
    palette.setColor(QPalette.Base, QColor(255, 255, 255))
    palette.setColor(QPalette.AlternateBase, QColor(240, 240, 240))
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.black)
    palette.setColor(QPalette.PlaceholderText, QColor(0, 0, 0, 120))
    palette.setColor(QPalette.Text, QColor(0, 0, 0))
    palette.setColor(QPalette.Button, QColor(245, 245, 245))
    palette.setColor(QPalette.ButtonText, QColor(0, 0, 0))
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, QColor(0, 102, 204))
    palette.setColor(QPalette.LinkVisited, QColor(102, 0, 204))
    palette.setColor(QPalette.Highlight, QColor(51, 153, 255))
    palette.setColor(QPalette.HighlightedText, Qt.white)
    _disabled(palette, QColor(245, 245, 245), QColor(0, 0, 0, 100))
    return palette


def dark_mode():
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(15, 15, 15))
    palette.setColor(QPalette.AlternateBase, QColor(30, 30, 30))
    palette.setColor(QPalette.ToolTipBase, QColor(15, 15, 15))
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.PlaceholderText, QColor(255, 255, 255, 110))
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(30, 30, 30))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, QColor(255, 82, 82))
    palette.setColor(QPalette.Link, QColor(117, 180, 255))
    palette.setColor(QPalette.LinkVisited, QColor(190, 130, 255))
    palette.setColor(QPalette.Highlight, QColor(117, 180, 255))
    palette.setColor(QPalette.HighlightedText, Qt.black)
    _disabled(palette, QColor(30, 30, 30), QColor(255, 255, 255, 90))
    return palette


def tokyo_night():
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(26, 27, 38))
    palette.setColor(QPalette.WindowText, QColor(192, 202, 245))
    palette.setColor(QPalette.Base, QColor(22, 23, 34))
    palette.setColor(QPalette.AlternateBase, QColor(26, 27, 38))
    palette.setColor(QPalette.ToolTipBase, QColor(22, 23, 34))
    palette.setColor(QPalette.ToolTipText, QColor(192, 202, 245))
    palette.setColor(QPalette.PlaceholderText, QColor(192, 202, 245, 100))
    palette.setColor(QPalette.Text, QColor(192, 202, 245))
    palette.setColor(QPalette.Button, QColor(35, 38, 52))
    palette.setColor(QPalette.ButtonText, QColor(192, 202, 245))
    palette.setColor(QPalette.BrightText, QColor(255, 122, 138))
    palette.setColor(QPalette.Link, QColor(125, 207, 255))
    palette.setColor(QPalette.LinkVisited, QColor(187, 154, 247))
    palette.setColor(QPalette.Highlight, QColor(144, 122, 255))
    palette.setColor(QPalette.HighlightedText, Qt.white)
    _disabled(palette, QColor(26, 27, 38), QColor(192, 202, 245, 85))
    return palette
