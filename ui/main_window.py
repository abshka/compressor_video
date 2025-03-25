import os
import subprocess
import time
import signal
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QPushButton,
                             QHBoxLayout, QLabel, QFileDialog, QComboBox,
                             QSlider, QProgressBar, QMessageBox, QGroupBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from video_compressor.compressor import VideoCompressor


# Поток для сжатия одного файла
class CompressionThread(QThread):
    progress_update = pyqtSignal(int)
    compression_finished = pyqtSignal(bool, str, float, float, float)  # Добавлены размеры

    def __init__(self, input_file, output_file, codec, crf, hw_accel):
        super().__init__()
        self.input_file = input_file
        self.output_file = output_file
        self.codec = codec
        self.crf = crf
        self.hw_accel = hw_accel
        self.compressor = VideoCompressor()
        self.process = None

    def run(self):
        try:
            start_time = time.time()
            input_size_mb = os.path.getsize(self.input_file) / (1024 * 1024)
            self.compressor.compress_video(
                self.input_file,
                self.output_file,
                self.codec,
                self.crf,
                self.hw_accel,
                self.progress_update.emit
            )
            elapsed_time = time.time() - start_time
            output_size_mb = os.path.getsize(self.output_file) / (1024 * 1024) if os.path.exists(
                self.output_file) else 0
            self.compression_finished.emit(True, "Сжатие видео успешно завершено", elapsed_time, input_size_mb,
                                           output_size_mb)
        except Exception as e:
            elapsed_time = time.time() - start_time if 'start_time' in locals() else 0
            self.compression_finished.emit(False, f"Ошибка при сжатии видео: {str(e)}", elapsed_time, 0, 0)
        finally:
            if self.process and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()

    def stop(self):
        """Безопасная остановка процесса сжатия"""
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.wait()


# Поток для сжатия папки
class FolderCompressionThread(QThread):
    progress_update = pyqtSignal(int, str, int)  # Общий процент, текущий файл, процент текущего файла
    compression_finished = pyqtSignal(bool, str, float, float, float)  # Добавлены размеры

    def __init__(self, input_folder, output_folder, codec, crf, hw_accel, video_files):
        super().__init__()
        self.input_folder = input_folder
        self.output_folder = output_folder
        self.codec = codec
        self.crf = crf
        self.hw_accel = hw_accel
        self.video_files = video_files
        self.compressor = VideoCompressor()
        self.running = True

    def run(self):
        try:
            start_time = time.time()
            total_input_size_mb = 0
            total_output_size_mb = 0
            total_files = len(self.video_files)

            # Подсчет общего количества файлов для вычисления прогресса
            total_processed = 0

            for i, video_file in enumerate(self.video_files, 1):
                if not self.running:
                    break

                input_size_mb = os.path.getsize(video_file) / (1024 * 1024)
                total_input_size_mb += input_size_mb
                base_name, ext = os.path.splitext(os.path.basename(video_file))
                if self.codec == "vp9":
                    output_ext = ".webm"
                elif self.codec == "av1":
                    output_ext = ".mkv"
                else:
                    output_ext = ".mp4"
                output_file = os.path.join(self.output_folder, f"{base_name}_compressed{output_ext}")

                # Расчет прогресса: завершенные файлы + прогресс текущего файла
                def progress_callback(percent):
                    overall_percent = int((total_processed + percent / 100) / total_files * 100)
                    self.progress_update.emit(overall_percent, os.path.basename(video_file), percent)

                # Обработка текущего файла
                self.compressor.compress_video(
                    video_file,
                    output_file,
                    self.codec,
                    self.crf,
                    self.hw_accel,
                    progress_callback
                )

                output_size_mb = os.path.getsize(output_file) / (1024 * 1024) if os.path.exists(output_file) else 0
                total_output_size_mb += output_size_mb

                # Увеличиваем счетчик завершенных файлов
                total_processed += 1

                # Обновляем общий прогресс
                overall_percent = int(total_processed / total_files * 100)
                self.progress_update.emit(overall_percent, f"Завершено {i}/{total_files}", 100)

            # Финальное обновление прогресса
            self.progress_update.emit(overall_percent, f"Завершено {i}/{total_files}", 100)
            elapsed_time = time.time() - start_time
            self.compression_finished.emit(True, "Сжатие всех видео успешно завершено", elapsed_time,
                                           total_input_size_mb, total_output_size_mb)
        except Exception as e:
            elapsed_time = time.time() - start_time if 'start_time' in locals() else 0
            self.compression_finished.emit(False, f"Ошибка при сжатии видео: {str(e)}", elapsed_time, 0, 0)

    def stop(self):
        """Безопасная остановка процесса сжатия"""
        self.running = False


# Главное окно приложения
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.input_path = ""
        self.is_folder = False
        self.output_folder = ""
        self.compression_thread = None
        self.compressor = VideoCompressor()
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Компрессор видео")
        self.setGeometry(100, 100, 600, 500)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        # Выбор входного файла или папки
        input_layout = QHBoxLayout()
        self.input_label = QLabel("Входной файл/папка: не выбран")
        input_file_button = QPushButton("Выбрать файл")
        input_file_button.clicked.connect(self.select_input_file)
        input_folder_button = QPushButton("Выбрать папку")
        input_folder_button.clicked.connect(self.select_input_folder)
        input_layout.addWidget(self.input_label)
        input_layout.addWidget(input_file_button)
        input_layout.addWidget(input_folder_button)
        main_layout.addLayout(input_layout)

        # Выбор выходной папки
        output_layout = QHBoxLayout()
        self.output_label = QLabel("Выходная папка: не выбрана")
        output_button = QPushButton("Выбрать папку для сохранения")
        output_button.clicked.connect(self.select_output_folder)
        output_layout.addWidget(self.output_label)
        output_layout.addWidget(output_button)
        main_layout.addLayout(output_layout)

        # Настройки компрессии
        codec_group = QGroupBox("Настройки компрессии")
        codec_layout = QVBoxLayout()

        # Выбор кодека
        codec_selector_layout = QHBoxLayout()
        codec_selector_layout.addWidget(QLabel("Кодек:"))
        self.codec_combo = QComboBox()
        self.codec_combo.addItems(["h264", "h265 (HEVC)", "VP9", "AV1"])
        codec_selector_layout.addWidget(self.codec_combo)
        codec_layout.addLayout(codec_selector_layout)

        # Выбор качества (CRF)
        crf_layout = QHBoxLayout()
        crf_layout.addWidget(QLabel("Качество (CRF):"))
        self.crf_slider = QSlider(Qt.Horizontal)
        self.crf_slider.setRange(0, 51)
        self.crf_slider.setValue(23)
        self.crf_label = QLabel("23")
        self.crf_slider.valueChanged.connect(self.on_quality_changed)
        crf_layout.addWidget(self.crf_slider)
        crf_layout.addWidget(self.crf_label)
        codec_layout.addLayout(crf_layout)

        # Оценка размера
        size_estimation_layout = QHBoxLayout()
        size_estimation_layout.addWidget(QLabel("Оценка размера:"))
        self.size_estimate_label = QLabel("N/A")
        size_estimation_layout.addWidget(self.size_estimate_label)
        codec_layout.addLayout(size_estimation_layout)

        # Аппаратное ускорение
        hw_accel_layout = QHBoxLayout()
        hw_accel_layout.addWidget(QLabel("Аппаратное ускорение:"))
        self.hw_accel_combo = QComboBox()
        self.hw_accel_combo.addItems(["Нет", "NVIDIA (NVENC)", "AMD (AMF)", "Intel (QSV)"])
        hw_accel_layout.addWidget(self.hw_accel_combo)
        codec_layout.addLayout(hw_accel_layout)

        codec_group.setLayout(codec_layout)
        main_layout.addWidget(codec_group)

        # Прогресс-бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        # Первая строка статуса: текущий файл и прогресс файла
        status_row_1 = QHBoxLayout()
        self.current_file_label = QLabel("Текущий файл: N/A")
        self.file_progress_label = QLabel("Прогресс файла: 0%")
        status_row_1.addWidget(self.current_file_label)
        status_row_1.addWidget(self.file_progress_label)
        main_layout.addLayout(status_row_1)

        # Вторая строка статуса: общий прогресс и ETA
        status_row_2 = QHBoxLayout()
        self.overall_progress_label = QLabel("Общий прогресс: 0/0")
        self.eta_label = QLabel("Осталось времени: --:--")
        status_row_2.addWidget(self.overall_progress_label)
        status_row_2.addWidget(self.eta_label)
        main_layout.addLayout(status_row_2)

        # Кнопка запуска сжатия
        self.compress_button = QPushButton("Сжать видео")
        self.compress_button.clicked.connect(self.compress_video)
        self.compress_button.setEnabled(False)
        main_layout.addWidget(self.compress_button)

        # Подключение обновления оценки размера
        self.codec_combo.currentIndexChanged.connect(self.update_size_estimate)

    def on_quality_changed(self, value):
        self.crf_label.setText(str(value))
        self.update_size_estimate()

    def select_input_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите видео для сжатия",
            "",
            "Видео файлы (*.mp4 *.mkv *.avi *.mov *.wmv *.webm);;Все файлы (*)"
        )
        if file_path:
            self.input_path = file_path
            self.is_folder = False
            self.input_label.setText(f"Входной файл: {os.path.basename(file_path)}")
            self.update_compress_button()
            self.update_size_estimate()

    def select_input_folder(self):
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку с видео",
            ""
        )
        if folder_path:
            self.input_path = folder_path
            self.is_folder = True
            video_files = self.get_video_files(folder_path)
            self.input_label.setText(f"Входная папка: {os.path.basename(folder_path)} ({len(video_files)} видео)")
            self.update_compress_button()
            self.update_size_estimate()

    def select_output_folder(self):
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку для сохранения сжатых видео",
            ""
        )
        if folder_path:
            self.output_folder = folder_path
            self.output_label.setText(f"Выходная папка: {os.path.basename(folder_path)}")
            self.update_compress_button()

    def get_video_files(self, folder_path):
        video_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.webm']
        files = []
        for file in os.listdir(folder_path):
            if any(file.lower().endswith(ext) for ext in video_extensions) and 'compressed' not in file.lower():
                files.append(os.path.join(folder_path, file))
        return files

    def update_compress_button(self):
        self.compress_button.setEnabled(bool(self.input_path and self.output_folder))

    def update_size_estimate(self):
        if not self.input_path:
            self.size_estimate_label.setText("N/A")
            return

        codec = self.codec_combo.currentText().split(" ")[0].lower()
        crf = self.crf_slider.value()

        try:
            if self.is_folder:
                video_files = self.get_video_files(self.input_path)
                total_estimated_size = 0
                for video_file in video_files:
                    estimated_size = self.compressor.estimate_output_size(video_file, codec, crf)
                    total_estimated_size += estimated_size
                estimated_size = total_estimated_size
            else:
                estimated_size = self.compressor.estimate_output_size(self.input_path, codec, crf)

            if estimated_size >= 1024:
                self.size_estimate_label.setText(f"{estimated_size / 1024:.2f} ГБ")
            else:
                self.size_estimate_label.setText(f"{estimated_size:.2f} МБ")
        except Exception as e:
            self.size_estimate_label.setText("Ошибка оценки")
            print(f"Ошибка при оценке размера: {str(e)}")

    def compress_video(self):
        if not (self.input_path and self.output_folder):
            QMessageBox.warning(self, "Предупреждение", "Выберите входной файл/папку и выходную папку")
            return

        codec = self.codec_combo.currentText().split(" ")[0].lower()
        crf = self.crf_slider.value()
        hw_accel = self.hw_accel_combo.currentText()

        if hw_accel == "Нет":
            hw_accel = None
        elif "NVIDIA" in hw_accel:
            hw_accel = "nvidia"
        elif "AMD" in hw_accel:
            hw_accel = "amd"
        elif "Intel" in hw_accel:
            hw_accel = "intel"

        self.compress_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.current_file_label.setText("Текущий файл: N/A")
        self.file_progress_label.setText("Прогресс файла: 0%")
        self.overall_progress_label.setText("Общий прогресс: 0/0")
        self.eta_label.setText("Осталось времени: --:--")

        # Установка начального времени для расчёта ETA
        self.start_time = time.time()
        self.last_progress_update = 0

        if self.is_folder:
            video_files = self.get_video_files(self.input_path)
            if not video_files:
                QMessageBox.warning(self, "Предупреждение", "В выбранной папке нет видео-файлов")
                self.compress_button.setEnabled(True)
                return

            self.compression_thread = FolderCompressionThread(
                self.input_path,
                self.output_folder,
                codec,
                crf,
                hw_accel,
                video_files
            )
            self.total_files = len(video_files)
            self.overall_progress_label.setText(f"Общий прогресс: 0/{self.total_files}")
            self.compression_thread.progress_update.connect(self.update_folder_progress)
            self.compression_thread.compression_finished.connect(self.compression_completed)
            self.compression_thread.start()
        else:
            base_name, ext = os.path.splitext(os.path.basename(self.input_path))
            if codec == "vp9":
                output_ext = ".webm"
            elif codec == "av1":
                output_ext = ".mkv"
            else:
                output_ext = ".mp4"
            output_file = os.path.join(self.output_folder, f"{base_name}_compressed{output_ext}")
            self.compression_thread = CompressionThread(
                self.input_path,
                output_file,
                codec,
                crf,
                hw_accel
            )
            self.compression_thread.progress_update.connect(self.update_progress)
            self.compression_thread.compression_finished.connect(self.compression_completed)
            self.compression_thread.start()

    def update_progress(self, value):
        self.progress_bar.setValue(value)
        self.current_file_label.setText(f"Текущий файл: {os.path.basename(self.input_path)}")
        self.file_progress_label.setText(f"Прогресс файла: {value}%")
        self.overall_progress_label.setText("Общий прогресс: 1/1")

        # Расчёт ETA
        self.update_eta(value)

    def update_eta(self, progress):
        """Расчёт и обновление оставшегося времени"""
        if progress <= 0:
            self.eta_label.setText("Осталось времени: --:--")
            return

        current_time = time.time()
        elapsed = current_time - self.start_time

        # Избегаем деления на ноль
        if progress > 0:
            total_estimated = elapsed * 100 / progress
            remaining = total_estimated - elapsed

            # Форматируем оставшееся время
            if remaining < 60:
                time_str = f"{int(remaining)} сек."
            elif remaining < 3600:
                minutes = int(remaining // 60)
                seconds = int(remaining % 60)
                time_str = f"{minutes} мин. {seconds} сек."
            else:
                hours = int(remaining // 3600)
                minutes = int((remaining % 3600) // 60)
                time_str = f"{hours} ч. {minutes} мин."

            self.eta_label.setText(f"Осталось времени: {time_str}")

            # Сохраняем последнее обновление для оптимизации
            self.last_progress_update = progress

    def update_folder_progress(self, progress, file_name, file_progress):
        # Обновляем общий прогресс в прогресс-баре
        self.progress_bar.setValue(progress)
        self.current_file_label.setText(f"Текущий файл: {file_name}")

        # Обновляем прогресс текущего файла
        self.file_progress_label.setText(f"Прогресс файла: {file_progress}%")

        # Расчёт ETA для папки
        self.update_eta(progress)

        # Если это информация о завершении файла
        if file_name.startswith("Завершено"):
            self.overall_progress_label.setText(file_name)
        else:
            completed_files = int(progress * self.total_files / 100)
            self.overall_progress_label.setText(f"Обработано файлов: {completed_files}/{self.total_files}")

    def update_file_progress(self, progress, file_name):
        self.progress_bar.setValue(progress)
        self.current_file_label.setText(f"Текущий файл: {file_name}")
        self.file_progress_label.setText(f"Прогресс файла: {progress}%")

        # Расчёт ETA для папки
        self.update_eta(progress)

    def compression_completed(self, success, message, elapsed_time, input_size_mb, output_size_mb):
        self.compress_button.setEnabled(True)
        minutes = int(elapsed_time // 60)
        seconds = int(elapsed_time % 60)
        time_str = f"{minutes} мин. {seconds} сек."
        result_message = f"{message}\n\nВремя обработки: {time_str}"

        if success and input_size_mb > 0:
            compression_ratio = (output_size_mb / input_size_mb) * 100 if input_size_mb > 0 else 0
            result_message += f"\n\nИсходный размер: {input_size_mb:.2f} МБ\n"
            result_message += f"Конечный размер: {output_size_mb:.2f} МБ\n"
            result_message += f"Степень сжатия: {compression_ratio:.1f}%"

        if success:
            QMessageBox.information(self, "Успех", result_message)
        else:
            QMessageBox.critical(self, "Ошибка", result_message)

    def closeEvent(self, event):
        """Обработка закрытия окна"""
        if self.compression_thread and self.compression_thread.isRunning():
            self.compression_thread.stop()
        event.accept()
