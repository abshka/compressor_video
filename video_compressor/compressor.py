import os
import subprocess
import re
import time
import signal
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
            crf: Constant Rate Factor, параметр качества (0-51)
            hardware_acceleration: Тип аппаратного ускорения (nvidia, amd, intel или None)
            progress_callback: Функция обратного вызова для обновления прогресса (0-100)
        """
        if not os.path.exists(input_file):
            raise FileNotFoundError(f"Входной файл не найден: {input_file}")

        # Буферизация вывода для улучшения производительности
        process = None
        try:
            command = self._prepare_command(input_file, output_file, codec, crf, hardware_acceleration)

            # Запускаем процесс с правильной настройкой буферов и потоков
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                text=True,
                bufsize=1  # Построчная буферизация для более стабильной работы
            )

            duration = self._get_video_duration(input_file)

            if process.returncode is None:  # Проверяем, что процесс еще запущен
                if progress_callback:
                    self._monitor_progress(process, duration, progress_callback)
                else:
                    stdout, stderr = process.communicate()  # Ожидаем завершения и читаем все потоки

            if process and process.returncode != 0:
                stderr_output = process.stderr.read() if process and process.stderr else "Неизвестная ошибка"
                raise RuntimeError(f"Ошибка FFmpeg: {stderr_output}")

        except Exception as e:
            if process:
                # Корректное завершение процесса ffmpeg
                process.terminate()
                try:
                    process.wait(timeout=5)  # Ждем 5 секунд
                except subprocess.TimeoutExpired:
                    process.kill()  # Принудительное завершение
                    process.wait()
            raise e

    def _prepare_command(self, input_file, output_file, codec, crf, hardware_acceleration):
        """Подготовка команды ffmpeg с оптимизированными параметрами"""
        command = ["ffmpeg", "-i", input_file]

        # Добавляем оптимизированные параметры буферизации
        command.extend(["-thread_queue_size", "4096"])

        if hardware_acceleration:
            command.extend(self._get_hw_accel_args(codec, crf, hardware_acceleration))
        else:
            command.extend(self._get_software_codec_args(codec, crf))

        command.extend([
            "-c:a", "copy",
            "-progress", "-",
            "-nostats",
            "-y",
            output_file
        ])
        return command

    def _get_hw_accel_args(self, codec, crf, hardware_acceleration):
        """Получение оптимизированных параметров для аппаратного ускорения"""
        args = []
        if hardware_acceleration == "nvidia":
            if codec == "h264":
                args.extend(["-c:v", "h264_nvenc", "-preset", "p4", "-tune", "hq"])
            elif codec == "h265":
                args.extend(["-c:v", "hevc_nvenc", "-preset", "p4", "-tune", "hq"])
        elif hardware_acceleration == "amd":
            if codec == "h264":
                args.extend(["-c:v", "h264_amf", "-quality", "quality"])
            elif codec == "h265":
                args.extend(["-c:v", "hevc_amf", "-quality", "quality"])
        elif hardware_acceleration == "intel":
            if codec == "h264":
                args.extend(["-c:v", "h264_qsv", "-preset", "slower"])
            elif codec == "h265":
                args.extend(["-c:v", "hevc_qsv", "-preset", "slower"])

        if codec in ["h264", "h265"]:
            args.extend(["-crf", str(crf)])
        return args

    def _get_software_codec_args(self, codec: str, crf: int) -> list:
        """Возвращает аргументы для программного кодека"""
        if codec == "h264":
            return ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf)]
        elif codec == "h265":
            return ["-c:v", "libx265", "-preset", "medium", "-crf", str(crf)]
        elif codec == "vp9":
            vp9_crf = min(63, int(crf * 1.23))
            return ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(vp9_crf)]
        elif codec == "av1":
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
        """Оптимизированный мониторинг прогресса FFmpeg"""
        time_pattern = re.compile(r"out_time_ms=(\d+)")
        last_progress = -1
        last_update_time = 0
        update_interval = 0.5  # Интервал обновления в секундах

        # Используем безопасное чтение с обработкой закрытых потоков
        try:
            while process.poll() is None:
                try:
                    line = process.stdout.readline()
                    if not line:
                        time.sleep(0.1)  # Небольшая задержка, чтобы не загружать CPU
                        continue

                    match = time_pattern.search(line)
                    if match:
                        current_ms = int(match.group(1))
                        current_secs = current_ms / 1000000
                        progress = min(100, int((current_secs / total_duration) * 100))

                        current_time = time.time()
                        if (progress != last_progress and
                                current_time - last_update_time >= update_interval):
                            progress_callback(progress)
                            last_progress = progress
                            last_update_time = current_time
                except (ValueError, IOError, BrokenPipeError):
                    # Обработка возможных исключений при чтении потока
                    break

            # Собираем оставшийся вывод, чтобы избе��ать блокировки буферов
            try:
                process.communicate()
            except Exception:
                pass

            # Завершающее обновление прогресса
            if process.returncode == 0:
                progress_callback(100)

        except Exception as e:
            # Перехватываем любые исключения при мониторинге, чтобы не крашить программу
            print(f"Ошибка при мониторинге прогресса: {e}")

    def estimate_output_size(self, input_file: str, codec: str, crf: int) -> float:
        """Оценивает размер выходного файла в МБ"""
        if not os.path.exists(input_file):
            return 0.0

        input_size_mb = os.path.getsize(input_file) / (1024 * 1024)

        try:
            original_bitrate = self._get_video_bitrate(input_file)
            video_duration = self._get_video_duration(input_file)
            if original_bitrate > 0 and video_duration > 0:
                return self._estimate_using_bitrate(codec, crf, original_bitrate, video_duration)
        except Exception as e:
            print(f"Ошибка анализа битрейта: {e}")

        base_compression_ratio = {"h264": 0.35, "h265": 0.25, "vp9": 0.22, "av1": 0.18}
        crf_mid = 23
        crf_factor = 2 ** ((crf_mid - crf) / 6.0)
        compression_ratio = base_compression_ratio.get(codec, 0.35) * crf_factor
        compression_ratio = min(1.0, compression_ratio)
        estimated_size_mb = input_size_mb * compression_ratio
        return max(0.1, estimated_size_mb)

    def _get_video_bitrate(self, input_file: str) -> int:
        """Определяет битрейт видео в bps"""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=bit_rate",
            "-of", "default=noprint_wrappers=1:nokey=1",
            input_file
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return int(result.stdout.strip())
        except (ValueError, TypeError):
            filesize = os.path.getsize(input_file) * 8
            duration = self._get_video_duration(input_file)
            if duration > 0:
                return int(filesize / duration)
            return 0

    def _estimate_using_bitrate(self, codec: str, crf: int, original_bitrate: int, duration: float) -> float:
        """Оценивает размер на основе битрейта"""
        bitrate_reduction = {"h264": 0.35, "h265": 0.25, "vp9": 0.22, "av1": 0.18}
        crf_mid = 23
        crf_factor = 2 ** ((crf_mid - crf) / 6.0)
        reduction = bitrate_reduction.get(codec, 0.35)
        estimated_bitrate = original_bitrate * reduction * crf_factor
        estimated_size_mb = (estimated_bitrate * duration) / 8 / (1024 * 1024)
        return max(0.1, estimated_size_mb)
