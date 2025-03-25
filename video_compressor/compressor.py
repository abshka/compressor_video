import os
import subprocess
import re
import time
from typing import Callable, Optional

class VideoCompressor:
    """Класс для сжатия видео с использованием FFmpeg"""
    
    def __init__(self):
        self._check_ffmpeg()
    
    def _check_ffmpeg(self):
        """Проверяет наличие FFmpeg в системе"""
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        except (subprocess.SubprocessError, FileNotFoundError):
            raise RuntimeError(
                "FFmpeg не найден. Пожалуйста, установите FFmpeg и убедитесь, "
                "что он доступен в системном PATH."
            )
    
    def compress_video(
        self, 
        input_file: str, 
        output_file: str,
        codec: str = "h264",
        crf: int = 23,
        hardware_acceleration: Optional[str] = None,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> None:
        """
        Сжимает видео с указанными параметрами.
        
        Args:
            input_file: Путь к исходному видеофайлу
            output_file: Путь для сохранения сжатого видео
            codec: Кодек для сжатия (h264, h265, vp9, av1)
            crf: Constant Rate Factor, параметр качества (0-51), 
                 где меньшие значения означают лучшее качество
            hardware_acceleration: Тип аппаратного ускорения (nvidia, amd, intel или None)
            progress_callback: Функция обратного вызова для обновления прогресса (0-100)
        """
        if not os.path.exists(input_file):
            raise FileNotFoundError(f"Входной файл не найден: {input_file}")
            
        # Проверка и добавление расширения выходного файла, если отсутствует
        _, ext = os.path.splitext(output_file)
        if not ext:
            # Добавляем расширение в зависимости от выбранного кодека
            if codec in ["h264", "h265"]:
                output_file += ".mp4"
            elif codec == "vp9":
                output_file += ".webm"
            elif codec == "av1":
                output_file += ".mkv"
            else:
                output_file += ".mp4"  # По умолчанию mp4
            
        # Получаем общую продолжительность видео
        duration = self._get_video_duration(input_file)
        if duration <= 0:
            raise ValueError(f"Не удалось определить продолжительность видео: {input_file}")
        
        # Настраиваем параметры командной строки FFmpeg в зависимости от выбранных опций
        command = ["ffmpeg", "-i", input_file]
        
        # Настраиваем параметры кодека и аппаратного ускорения
        if hardware_acceleration:
            if hardware_acceleration == "nvidia":
                if codec == "h264":
                    command.extend(["-c:v", "h264_nvenc", "-preset", "slow"])
                elif codec == "h265":
                    command.extend(["-c:v", "hevc_nvenc", "-preset", "slow"])
                else:
                    # Для VP9 и AV1 на NVIDIA используем программное кодирование
                    command.extend(self._get_software_codec_args(codec, crf))
            elif hardware_acceleration == "amd":
                if codec == "h264":
                    command.extend(["-c:v", "h264_amf"])
                elif codec == "h265":
                    command.extend(["-c:v", "hevc_amf"])
                else:
                    command.extend(self._get_software_codec_args(codec, crf))
            elif hardware_acceleration == "intel":
                if codec == "h264":
                    command.extend(["-c:v", "h264_qsv"])
                elif codec == "h265":
                    command.extend(["-c:v", "hevc_qsv"])
                else:
                    command.extend(self._get_software_codec_args(codec, crf))
                    
            # Добавляем CRF для hw кодеков
            if codec in ["h264", "h265"]:
                command.extend(["-crf", str(crf)])
        else:
            # Программное кодирование
            command.extend(self._get_software_codec_args(codec, crf))
        
        # Копируем аудио без изменений
        command.extend(["-c:a", "copy"])
        
        # Показываем прогресс
        command.extend(["-progress", "-", "-nostats"])
        
        # Указываем выходной файл и перезаписываем, если существует
        command.extend(["-y", output_file])
        
        # Запускаем процесс FFmpeg
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            text=True,
            bufsize=1
        )
        
        # Отслеживаем прогресс
        if progress_callback:
            self._monitor_progress(process, duration, progress_callback)
        else:
            process.wait()
            
        # Проверяем результат
        if process.returncode != 0:
            stderr = process.stderr.read() if hasattr(process.stderr, 'read') else "Неизвестная ошибка"
            raise RuntimeError(f"Ошибка FFmpeg: {stderr}")
    
    def _get_software_codec_args(self, codec: str, crf: int) -> list:
        """Возвращает аргументы командной строки для программного кодека"""
        if codec == "h264":
            return ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf)]
        elif codec == "h265":
            return ["-c:v", "libx265", "-preset", "medium", "-crf", str(crf)]
        elif codec == "vp9":
            # VP9 использует другую шкалу CRF (0-63), адаптируем значение
            vp9_crf = min(63, int(crf * 1.23))
            return ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(vp9_crf)]
        elif codec == "av1":
            # AV1 использует свою шкалу и параметры
            return ["-c:v", "libaom-av1", "-crf", str(crf), "-b:v", "0", "-strict", "experimental"]
        else:
            raise ValueError(f"Неподдерживаемый кодек: {codec}")
    
    def _get_video_duration(self, input_file: str) -> float:
        """Определяет длительность видео в секундах"""
        cmd = [
            "ffprobe", 
            "-v", "error", 
            "-show_entries", "format=duration", 
            "-of", "default=noprint_wrappers=1:nokey=1", 
            input_file
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        try:
            return float(result.stdout.strip())
        except ValueError:
            return 0.0
    
    def _monitor_progress(
        self, 
        process: subprocess.Popen, 
        total_duration: float, 
        progress_callback: Callable[[int], None]
    ) -> None:
        """Мониторит прогресс FFmpeg и вызывает callback с процентом завершения"""
        time_pattern = re.compile(r"out_time_ms=(\d+)")
        last_update = 0
        
        for line in process.stdout:
            match = time_pattern.search(line)
            if match:
                current_ms = int(match.group(1))
                current_secs = current_ms / 1000000
                progress = min(100, int((current_secs / total_duration) * 100))
                
                # Обновляем прогресс не чаще чем раз в 0.5 сек
                current_time = time.time()
                if progress != last_update and current_time - last_update > 0.5:
                    progress_callback(progress)
                    last_update = current_time
        
        # Дожидаемся завершения процесса
        process.wait()
        
        # Финальное обновление прогресса
        if process.returncode == 0:
            progress_callback(100)

