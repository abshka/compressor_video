import os
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QPushButton,
                            QHBoxLayout, QLabel, QFileDialog, QComboBox,
                            QSlider, QProgressBar, QMessageBox, QGroupBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from video_compressor.compressor import VideoCompressor

class CompressionThread(QThread):
    progress_update = pyqtSignal(int)
    compression_finished = pyqtSignal(bool, str)
    
    def __init__(self, input_file, output_file, codec, crf, hw_accel):
        super().__init__()
        self.input_file = input_file
        self.output_file = output_file
        self.codec = codec
        self.crf = crf
        self.hw_accel = hw_accel
        self.compressor = VideoCompressor()
        
    def run(self):
        try:
            self.compressor.compress_video(
                self.input_file, 
                self.output_file,
                self.codec,
                self.crf,
                self.hw_accel,
                self.progress_update.emit
            )
            self.compression_finished.emit(True, "Сжатие видео успешно завершено")
        except Exception as e:
            self.compression_finished.emit(False, f"Ошибка при сжатии видео: {str(e)}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.input_file = ""
        self.output_file = ""
        self.compression_thread = None
        
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("Компрессор видео")
        self.setGeometry(100, 100, 600, 500)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)
        
        # Выбор входного файла
        input_layout = QHBoxLayout()
        self.input_label = QLabel("Входной файл: не выбран")
        input_button = QPushButton("Выбрать файл")
        input_button.clicked.connect(self.select_input_file)
        input_layout.addWidget(self.input_label)
        input_layout.addWidget(input_button)
        main_layout.addLayout(input_layout)
        
        # Выбор выходного файла
        output_layout = QHBoxLayout()
        self.output_label = QLabel("Выходной файл: не выбран")
        output_button = QPushButton("Сохранить как")
        output_button.clicked.connect(self.select_output_file)
        output_layout.addWidget(self.output_label)
        output_layout.addWidget(output_button)
        main_layout.addLayout(output_layout)
        
        # Группа настроек кодека
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
        self.crf_slider.setRange(0, 51)  # CRF для x264/x265 от 0 (лучшее) до 51 (худшее)
        self.crf_slider.setValue(23)  # Значение по умолчанию
        self.crf_label = QLabel("23")
        self.crf_slider.valueChanged.connect(lambda v: self.crf_label.setText(str(v)))
        crf_layout.addWidget(self.crf_slider)
        crf_layout.addWidget(self.crf_label)
        codec_layout.addLayout(crf_layout)
        
        # Аппаратное ускорение
        hw_accel_layout = QHBoxLayout()
        hw_accel_layout.addWidget(QLabel("Аппаратное ускорение:"))
        self.hw_accel_combo = QComboBox()
        self.hw_accel_combo.addItems(["Нет", "NVIDIA (NVENC)", "AMD (AMF)", "Intel (QSV)"])
        hw_accel_layout.addWidget(self.hw_accel_combo)
        codec_layout.addLayout(hw_accel_layout)
        
        codec_group.setLayout(codec_layout)
        main_layout.addWidget(codec_group)
        
        # Прогресс бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)
        
        # Кнопка запуска компрессии
        self.compress_button = QPushButton("Сжать видео")
        self.compress_button.clicked.connect(self.compress_video)
        self.compress_button.setEnabled(False)
        main_layout.addWidget(self.compress_button)
    
    def select_input_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите видео для сжатия",
            "",
            "Видео файлы (*.mp4 *.mkv *.avi *.mov *.wmv *.webm);;Все файлы (*)"
        )
        
        if file_path:
            self.input_file = file_path
            self.input_label.setText(f"Входной файл: {os.path.basename(file_path)}")
            self.update_compress_button()
    
    def select_output_file(self):
        # Получаем текущий выбранный кодек для определения фильтра и расширения
        codec = self.codec_combo.currentText().split(" ")[0].lower()
        
        default_ext = ".mp4"
        default_filter = "MP4 файл (*.mp4)"
        
        if codec == "vp9":
            default_ext = ".webm"
            default_filter = "WebM файл (*.webm)"
        elif codec == "av1":
            default_ext = ".mkv"
            default_filter = "MKV файл (*.mkv)"
        
        # Определяем начальное имя файла на основе входного файла
        suggested_name = ""
        if self.input_file:
            base_name = os.path.splitext(os.path.basename(self.input_file))[0]
            suggested_name = os.path.join(os.path.dirname(self.input_file), f"{base_name}_compressed{default_ext}")
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить сжатое видео",
            suggested_name,
            f"{default_filter};;MP4 файл (*.mp4);;MKV файл (*.mkv);;WebM файл (*.webm);;Все файлы (*)"
        )
        
        if file_path:
            # Проверяем наличие расширения и добавляем его при необходимости
            _, ext = os.path.splitext(file_path)
            if not ext:
                file_path += default_ext
                
            self.output_file = file_path
            self.output_label.setText(f"Выходной файл: {os.path.basename(file_path)}")
            self.update_compress_button()
    
    def update_compress_button(self):
        self.compress_button.setEnabled(bool(self.input_file and self.output_file))
    
    def compress_video(self):
        if not (self.input_file and self.output_file):
            QMessageBox.warning(self, "Предупреждение", "Выберите входной и выходной файлы")
            return
        
        # Проверка, что файл имеет расширение
        _, ext = os.path.splitext(self.output_file)
        if not ext:
            codec = self.codec_combo.currentText().split(" ")[0].lower()
            if codec in ["h264", "h265"]:
                self.output_file += ".mp4"
            elif codec == "vp9":
                self.output_file += ".webm"
            elif codec == "av1":
                self.output_file += ".mkv"
            else:
                self.output_file += ".mp4"
            self.output_label.setText(f"Выходной файл: {os.path.basename(self.output_file)}")
        
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
        
        self.compression_thread = CompressionThread(
            self.input_file,
            self.output_file,
            codec,
            crf,
            hw_accel
        )
        
        self.compression_thread.progress_update.connect(self.update_progress)
        self.compression_thread.compression_finished.connect(self.compression_completed)
        self.compression_thread.start()
    
    def update_progress(self, value):
        self.progress_bar.setValue(value)
    
    def compression_completed(self, success, message):
        self.compress_button.setEnabled(True)
        
        if success:
            QMessageBox.information(self, "Успех", message)
        else:
            QMessageBox.critical(self, "Ошибка", message)

