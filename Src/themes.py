from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette


def _bevels(palette, light, midlight, dark, mid, shadow, accent):
    palette.setColor(QPalette.Light, QColor(*light))
    palette.setColor(QPalette.Midlight, QColor(*midlight))
    palette.setColor(QPalette.Dark, QColor(*dark))
    palette.setColor(QPalette.Mid, QColor(*mid))
    palette.setColor(QPalette.Shadow, QColor(*shadow))
    palette.setColor(QPalette.Accent, QColor(*accent))


def _disabled(palette, window, text, base, highlight):
    group = QPalette.Disabled
    palette.setColor(group, QPalette.Window, window)
    palette.setColor(group, QPalette.WindowText, text)
    palette.setColor(group, QPalette.Text, text)
    palette.setColor(group, QPalette.ButtonText, text)
    palette.setColor(group, QPalette.Base, base)
    palette.setColor(group, QPalette.PlaceholderText, text)
    palette.setColor(group, QPalette.ToolTipText, text)
    palette.setColor(group, QPalette.BrightText, text)
    palette.setColor(group, QPalette.Highlight, highlight)
    palette.setColor(group, QPalette.HighlightedText, window)


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
    _bevels(
        palette,
        light=(255, 255, 255),
        midlight=(229, 229, 229),
        dark=(160, 160, 160),
        mid=(128, 128, 128),
        shadow=(70, 70, 70),
        accent=(51, 153, 255),
    )
    _disabled(
        palette,
        window=QColor(245, 245, 245),
        text=QColor(0, 0, 0, 100),
        base=QColor(255, 255, 255),
        highlight=QColor(160, 195, 232),
    )
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
    _bevels(
        palette,
        light=(60, 60, 60),
        midlight=(45, 45, 45),
        dark=(10, 10, 10),
        mid=(22, 22, 22),
        shadow=(5, 5, 5),
        accent=(117, 180, 255),
    )
    _disabled(
        palette,
        window=QColor(30, 30, 30),
        text=QColor(255, 255, 255, 90),
        base=QColor(15, 15, 15),
        highlight=QColor(58, 90, 122),
    )
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
    _bevels(
        palette,
        light=(45, 47, 60),
        midlight=(35, 37, 50),
        dark=(14, 15, 22),
        mid=(24, 26, 36),
        shadow=(8, 9, 14),
        accent=(144, 122, 255),
    )
    _disabled(
        palette,
        window=QColor(26, 27, 38),
        text=QColor(192, 202, 245, 85),
        base=QColor(22, 23, 34),
        highlight=QColor(72, 61, 128),
    )
    return palette
