"""Convert the app logo into a multi-resolution Windows ICO without Pillow.

Run from any directory: python tools/build_icon.py
"""

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter


def build_icon() -> Path:
    graphics = Path(__file__).resolve().parents[1] / "app" / "ui" / "graphics"
    image = QImage(str(graphics / "logo.png"))
    if image.isNull():
        raise RuntimeError("Could not load app/ui/graphics/logo.png")
    frames: list[tuple[int, bytes]] = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        scaled = image.scaled(
            size, size, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        canvas = QImage(size, size, QImage.Format.Format_ARGB32)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.drawImage((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
        painter.end()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not canvas.save(buffer, "PNG"):
            raise RuntimeError(f"Could not encode {size}px icon frame")
        frames.append((size, bytes(buffer.data())))
    offset = 6 + 16 * len(frames)
    entries = []
    for size, data in frames:
        dimension = 0 if size == 256 else size
        entries.append(struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    path = graphics / "logo.ico"
    path.write_bytes(struct.pack("<HHH", 0, 1, len(frames)) + b"".join(entries) + b"".join(data for _, data in frames))
    return path


if __name__ == "__main__":
    print(build_icon())
