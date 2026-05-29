from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Dict, Optional

import cv2
from PyQt6 import sip
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal, pyqtSlot, QObject
from PyQt6.QtGui import QFont, QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
    QWidget,
    QMessageBox,
    QDialog,
)

from ..ml.pose_detector import PoseDetector
from ..services.settings_service import (
    CALIBRATION_DURATION_SECONDS,
    CALIBRATION_TIMEOUT_MARGIN_SECONDS,
    SettingsService,
)


@dataclass
class CalibrationResult:
    posture_score: float
    neck_angle: float
    shoulder_delta: float


class CameraPreviewWidget(QLabel):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setText(self.tr("Здесь появится предпросмотр камеры"))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._camera_id = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_frame)
        self._capture: Optional[cv2.VideoCapture] = None

    def start(self, camera_id: int) -> None:
        self.stop()
        self._camera_id = camera_id
        capture = cv2.VideoCapture(self._camera_id)
        if not capture.isOpened() and sys.platform == "darwin":
            capture = cv2.VideoCapture(self._camera_id, cv2.CAP_AVFOUNDATION)
        if not capture or not capture.isOpened():
            self.setText(self.tr("Не удаётся открыть камеру"))
            return
        self._capture = capture
        self._timer.start(40)

    def stop(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
        if self._capture:
            self._capture.release()
            self._capture = None
        self.clear()

    def _update_frame(self) -> None:
        if not self._capture:
            return
        ret, frame = self._capture.read()
        if not ret:
            self.setText(self.tr("Поток с камеры недоступен"))
            return
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame.shape
        image = QImage(frame.data, w, h, ch * w, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(image).scaled(
            self.width(),
            self.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(pixmap)

    def resizeEvent(self, event):  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if self.pixmap():
            self.setPixmap(
                self.pixmap().scaled(
                    self.width(),
                    self.height(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )


class CalibrationWorker(QObject):
    """Background QObject that captures a baseline posture sample on a worker QThread.

    Opens the camera, runs PoseDetector for ``duration_seconds`` (default:
    CALIBRATION_DURATION_SECONDS = 6), averages posture_score / neck_angle /
    shoulder_vertical_delta across collected frames, and emits either
    ``finished(CalibrationResult)`` or ``failed(str)``.

    A QTimer in CalibrationPage cancels the worker after
    ``duration + CALIBRATION_TIMEOUT_MARGIN_SECONDS`` to handle camera hangs.
    """

    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        settings: SettingsService,
        duration_seconds: int = CALIBRATION_DURATION_SECONDS,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._duration = duration_seconds
        self._stop = False

    def cancel(self) -> None:
        self._stop = True

    @property
    def duration(self) -> int:
        return self._duration

    @pyqtSlot()
    def run(self) -> None:
        capture = None
        try:
            camera_id = self._settings.runtime.default_camera_id
            capture = cv2.VideoCapture(camera_id)
            if not capture.isOpened() and sys.platform == "darwin":
                capture.release()
                capture = cv2.VideoCapture(camera_id, cv2.CAP_AVFOUNDATION)

            if not capture or not capture.isOpened():
                self.failed.emit(
                    QApplication.translate(
                        "CalibrationWorker", "Нет доступа к камере"
                    )
                )
                return

            detector = PoseDetector(self._settings)
            start_time = time.time()
            collected: Dict[str, list] = {
                "posture_score": [],
                "neck_angle": [],
                "shoulder_delta": [],
            }

            while not self._stop and time.time() - start_time < self._duration:
                ret, frame = capture.read()
                if not ret:
                    time.sleep(0.05)
                    continue
                _, score, result_bundle = detector.process_frame(frame)
                if not result_bundle:
                    time.sleep(0.05)
                    continue
                metrics = (
                    result_bundle.metrics if hasattr(result_bundle, "metrics") else {}
                )
                collected["posture_score"].append(metrics.get("posture_score", score))
                collected["neck_angle"].append(metrics.get("neck_angle", 0.0))
                collected["shoulder_delta"].append(
                    metrics.get("shoulder_vertical_delta", 0.0)
                )
                time.sleep(0.05)

        except Exception as exc:  # noqa: BLE001 - propagate error to UI
            self.failed.emit(str(exc))
            return
        finally:
            if capture:
                capture.release()

        if self._stop:
            self.failed.emit(
                QApplication.translate("CalibrationWorker", "Калибровка отменена")
            )
            return

        if not collected["posture_score"]:
            self.failed.emit(
                QApplication.translate("CalibrationWorker", "Данные об осанке не получены")
            )
            return

        result = CalibrationResult(
            posture_score=float(
                sum(collected["posture_score"]) / len(collected["posture_score"])
            ),
            neck_angle=float(
                sum(collected["neck_angle"]) / len(collected["neck_angle"])
            ),
            shoulder_delta=float(
                sum(collected["shoulder_delta"]) / len(collected["shoulder_delta"])
            ),
        )
        self.finished.emit(result)


class WelcomePage(QWizardPage):
    """Opening wizard page — introduces the three-step onboarding flow."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setTitle(self.tr("Добро пожаловать в PostureControl"))
        self.setSubTitle(
            self.tr("Мы настроим ваш опыт за три быстрых шага.")
        )

        hero = QLabel(
            self.tr(
                "Хорошая осанка начинается с осознанности. Мы поможем вам настроить кадрирование камеры, изучить признаки правильной осанки и записать ваши личные базовые показатели, чтобы напоминания были персонализированными."
            )
        )
        hero.setWordWrap(True)
        hero_font = QFont()
        hero_font.setPointSize(hero_font.pointSize() + 2)
        hero_font.setBold(True)
        hero.setFont(hero_font)

        tips = QLabel(
            self.tr(
                "- Найдите хорошо освещённое место\n"
                "- Расположите камеру на уровне глаз\n"
                "- Сидите естественно — не нужно позировать!"
            )
        )
        tips.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addWidget(hero)
        layout.addSpacing(12)
        layout.addWidget(tips)
        layout.addStretch(1)
        self.setLayout(layout)


class CameraSetupPage(QWizardPage):
    """Wizard page showing a live camera preview for framing guidance.

    Starts CameraPreviewWidget when the page is entered and stops it on exit
    to release the capture handle before CalibrationWorker opens the same camera.
    """

    def __init__(
        self, settings: SettingsService, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setTitle(self.tr("Настройте камеру"))
        self.setSubTitle(
            self.tr("Расположитесь по центру, чтобы верхняя часть тела была в кадре.")
        )

        self.preview = CameraPreviewWidget()
        self.preview.setMinimumHeight(240)

        guidance = QLabel(
            self.tr(
                "Отрегулируйте положение, чтобы голова и плечи были видны. По возможности используйте естественное освещение."
            )
        )
        guidance.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addWidget(self.preview)
        layout.addSpacing(8)
        layout.addWidget(guidance)
        layout.addStretch(1)
        self.setLayout(layout)

    def initializePage(self) -> None:  # noqa: N802 - Qt override
        self.preview.start(self._settings.runtime.default_camera_id)

    def cleanupPage(self) -> None:  # noqa: N802 - Qt override
        self.preview.stop()

    def stop_preview(self) -> None:
        """Ensures the preview capture is released when leaving the page."""
        self.preview.stop()


class CalibrationPage(QWizardPage):
    """Wizard page that runs a 6-second baseline calibration via CalibrationWorker.

    Displays live status and results. The page is only "complete" (wizard's Next/Finish
    enabled) after a successful CalibrationResult is received. A timeout timer cancels
    a hung worker after duration + CALIBRATION_TIMEOUT_MARGIN_SECONDS seconds.
    """

    def __init__(
        self, settings: SettingsService, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setTitle(self.tr("Запишите базовые показатели"))
        self.setSubTitle(
            self.tr(
                "Мы сделаем короткий замер, чтобы анализировать осанку относительно вашего естественного положения."
            )
        )

        self.status_label = QLabel(
            self.tr(
                'Когда будете готовы, сядьте удобно и нажмите "Начать калибровку".'
            )
        )
        self.status_label.setWordWrap(True)

        self.results_label = QLabel("")
        self.results_label.setWordWrap(True)

        self.start_button = QPushButton(self.tr("Начать калибровку"))
        self.start_button.clicked.connect(self._begin_calibration)

        layout = QVBoxLayout()
        layout.addWidget(self.status_label)
        layout.addSpacing(12)
        layout.addWidget(self.start_button)
        layout.addSpacing(12)
        layout.addWidget(self.results_label)
        layout.addStretch(1)
        self.setLayout(layout)

        self._thread: Optional[QThread] = None
        self._worker: Optional[CalibrationWorker] = None
        self._metrics: Optional[CalibrationResult] = None
        self._timeout: Optional[QTimer] = None

    def _begin_calibration(self) -> None:
        if self._thread and self._thread.isRunning():
            return
        self.start_button.setEnabled(False)
        self.status_label.setText(
            self.tr("Сбор данных... Сохраняйте неподвижность шесть секунд.")
        )

        worker = CalibrationWorker(self._settings)
        thread = QThread(self)
        worker.moveToThread(thread)

        worker.finished.connect(self._handle_success)
        worker.failed.connect(self._handle_failure)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.started.connect(worker.run)

        self._worker = worker
        self._thread = thread
        thread.start()

        if not self._timeout:
            self._timeout = QTimer(self)
            self._timeout.setSingleShot(True)
            self._timeout.timeout.connect(self._handle_timeout)
        self._timeout.start(
            (worker.duration + CALIBRATION_TIMEOUT_MARGIN_SECONDS) * 1000
        )

    def _handle_success(self, result: CalibrationResult) -> None:
        self._metrics = result
        self.start_button.setEnabled(True)
        self.status_label.setText(self.tr("Базовые показатели записаны."))
        self.results_label.setText(
            self.tr(
                "- Средняя оценка осанки: {score:.1f}%\n"
                "- Угол шеи: {neck:.1f} deg\n"
                "- Дельта баланса плеч: {delta:.3f}"
            ).format(
                score=result.posture_score,
                neck=result.neck_angle,
                delta=result.shoulder_delta,
            )
        )
        self._cleanup_worker()
        self.completeChanged.emit()

    def _handle_failure(self, message: str) -> None:
        self.start_button.setEnabled(True)
        self.status_label.setText(self.tr("Калибровка не удалась"))
        QMessageBox.warning(self, self.tr("Calibration"), message)
        self._cleanup_worker()

    def _handle_timeout(self) -> None:
        if self._worker:
            self._worker.cancel()
        else:
            self._cleanup_worker()

    def _cleanup_worker(self) -> None:
        if self._timeout and self._timeout.isActive():
            self._timeout.stop()
        thread = self._thread
        worker = self._worker
        self._thread = None
        self._worker = None

        def _is_alive(obj: Optional[QObject]) -> bool:
            return obj is not None and not sip.isdeleted(obj)

        if _is_alive(thread):
            if thread.isRunning():
                thread.quit()
                thread.wait(2000)
            thread.deleteLater()
        if _is_alive(worker):
            worker.deleteLater()

    def isComplete(self) -> bool:  # noqa: N802 - Qt override
        return self._metrics is not None

    def metrics(self) -> Optional[CalibrationResult]:
        return self._metrics


class OnboardingWizard(QWizard):
    def __init__(
        self, settings_service: SettingsService, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self._settings = settings_service
        self.setWindowTitle(self.tr("Настройка PostureControl"))
        self.setOption(QWizard.WizardOption.IndependentPages, False)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setMinimumWidth(500)

        self.welcome_page = WelcomePage()
        self.camera_page = CameraSetupPage(settings_service)
        self.calibration_page = CalibrationPage(settings_service)

        self._welcome_page_id = self.addPage(self.welcome_page)
        self._camera_page_id = self.addPage(self.camera_page)
        self._calibration_page_id = self.addPage(self.calibration_page)
        self._last_page_id = self.currentId()
        self.currentIdChanged.connect(self._handle_page_change)

        self._metrics: Optional[CalibrationResult] = None

    def accept(self) -> None:
        metrics = self.calibration_page.metrics()
        if metrics:
            self._settings.update_profile(
                has_completed_onboarding=True,
                baseline_posture_score=metrics.posture_score,
                baseline_neck_angle=metrics.neck_angle,
                baseline_shoulder_level=metrics.shoulder_delta,
            )
            self._settings.save_all()
            self._metrics = metrics
        super().accept()

    def collected_metrics(self) -> Optional[CalibrationResult]:
        return self._metrics

    def _handle_page_change(self, page_id: int) -> None:
        if self._last_page_id == self._camera_page_id and self.camera_page is not None:
            self.camera_page.stop_preview()
        self._last_page_id = page_id


def run_onboarding_if_needed(
    settings_service: SettingsService, parent: Optional[QWidget] = None
) -> bool:
    if settings_service.profile.has_completed_onboarding:
        return False
    wizard = OnboardingWizard(settings_service, parent)
    return wizard.exec() == QDialog.DialogCode.Accepted
