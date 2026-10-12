"""A short two-frame startup screen using the bundled Milly graphics."""

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCursor, QHideEvent, QPixmap, QShowEvent
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from .theme import PAGE, SECTION, UI_ROOT


class LoadingScreen(QWidget):
    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("loadingScreen")
        self.setWindowTitle("SillyScripts")
        self.setFixedSize(368, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE, PAGE, PAGE, PAGE)
        layout.setSpacing(SECTION)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setAccessibleName("Milly loading animation")
        layout.addWidget(self.image, 1)
        title = QLabel("Loading SillyScripts...")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setProperty("role", "pageHeading")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        self.frames = [
            QPixmap(str(UI_ROOT / "graphics" / name)).scaled(
                240, 300, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            for name in ("milly-1.png", "milly-2.png")
        ]
        self.frame_index = 0
        self._display_frame()
        self.timer = QTimer(self)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self._next_frame)

    def _display_frame(self) -> None:
        frame = self.frames[self.frame_index]
        if frame.isNull():
            self.image.setText("Loading…")
        else:
            self.image.setPixmap(frame)

    def _next_frame(self) -> None:
        self.frame_index = (self.frame_index + 1) % len(self.frames)
        self._display_frame()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is not None:
            self.move(screen.availableGeometry().center() - self.rect().center())
        self.timer.start()

    def hideEvent(self, event: QHideEvent) -> None:
        self.timer.stop()
        super().hideEvent(event)
