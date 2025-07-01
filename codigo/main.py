import os
import subprocess
from PIL import Image
from pillow_heif import register_heif_opener
import shutil
import concurrent.futures
import platform
import time
import sys
import datetime
import re

register_heif_opener()

# Cambia la base de recursos para PyInstaller
def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# Ajusta las rutas para recursos y configuración
BASE_DIRECTORY = resource_path("")
CONFIG_FILENAME = os.path.join(BASE_DIRECTORY, "extra", "config.txt")
REQUIREMENTS_FILENAME = os.path.join(BASE_DIRECTORY, "extra", "requeriments.txt")
SOURCE_DIRECTORY = os.path.join(BASE_DIRECTORY, "entrada")
OUTPUT_DIRECTORY = os.path.join(BASE_DIRECTORY, "salida")
HEIC_QUALITY = 70
HEVC_CRF = 28
HEVC_PRESET = "Fast 1080p30"
ENABLE_GPU_ACCELERATION = False
ENCODER_GPU = "amf_h265"
MAX_WORKERS = max(1, int(os.cpu_count() * 0.8)) if os.cpu_count() else 4
MAX_RETRIES_FILE_OPS = 15
RETRY_DELAY_FILE_OPS = 0.5
DEBUG_MODE = True
DEVELOPER_MODE = False

def clear_console():
    if os.name == 'nt':
        os.system('cls')
    else:
        os.system('clear')

def load_configuration():
    global SOURCE_DIRECTORY, OUTPUT_DIRECTORY, DEVELOPER_MODE
    config_path = os.path.join(BASE_DIRECTORY, CONFIG_FILENAME)
    default_source_subdir = "entrada"
    default_output_subdir = "salida"

    if os.path.exists(config_path):
        config_values = {}
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, value = line.split('=', 1)
                        config_values[key.strip()] = value.strip()
        except Exception:
            print(f"❌ Error al leer el archivo de configuración '{CONFIG_FILENAME}'. Se usarán las rutas por defecto.")

        if config_values.get("modo-desarrollador", "").upper() == "SI":
            SOURCE_DIRECTORY = os.path.join(BASE_DIRECTORY, "extra", "archivos-ejemplo")
            DEVELOPER_MODE = True
        else:
            source_dir_from_config = config_values.get("carpeta_entrada")
            output_dir_from_config = config_values.get("carpeta_salida")
            if source_dir_from_config:
                SOURCE_DIRECTORY = os.path.abspath(os.path.join(BASE_DIRECTORY, source_dir_from_config))
            if output_dir_from_config:
                OUTPUT_DIRECTORY = os.path.abspath(os.path.join(BASE_DIRECTORY, output_dir_from_config))
    else:
        print(f"⚠️ El archivo de configuración '{CONFIG_FILENAME}' no se encontró.")
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write("# Archivo de configuración para NEU (Necesito Espacio Urgente)\n\n")
                f.write(f"carpeta_entrada = {default_source_subdir}\n")
                f.write(f"carpeta_salida = {default_output_subdir}\n")
        except Exception as e:
            print(f"❌ Error al crear el archivo de configuración '{CONFIG_FILENAME}': {e}")

    os.makedirs(SOURCE_DIRECTORY, exist_ok=True)
    os.makedirs(OUTPUT_DIRECTORY, exist_ok=True)

load_configuration()

EXTERNAL_TOOLS_DIRECTORY = os.path.join(BASE_DIRECTORY, "extra")
LOG_FILENAME = os.path.join(BASE_DIRECTORY, "extra", "logs.txt")
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.gif', '.heic', '.heif')
VIDEO_EXTENSIONS = ('.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv')
original_stdout = sys.stdout
original_stderr = sys.stderr
log_file_handle = None

class CustomStream:
    def __init__(self, terminal_stream, file_stream):
        self.terminal = terminal_stream
        self.file = file_stream
    def write(self, message):
        self.terminal.write(message)
        self.file.write(message)
        self.flush()
    def flush(self):
        self.terminal.flush()
        self.file.flush()

def _debug_print(message):
    if DEBUG_MODE and log_file_handle:
        log_file_handle.write(f"DEBUG: {message}\n")
        log_file_handle.flush()

def get_human_readable_size(size_bytes):
    if size_bytes is None:
        return "N/A"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024**2:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024**3:
        return f"{size_bytes / (1024**2):.2f} MB"
    else:
        return f"{size_bytes / (1024**3):.2f} GB"

def format_time_short(seconds):
    if seconds is None:
        return "N/A"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02}h {m:02}m {s:02}s"

def check_binary_exists_in_path_or_dir(binary_name, specific_dir=None):
    if specific_dir:

        os.environ["PATH"] = specific_dir + os.pathsep + os.environ["PATH"]
        _debug_print(f"PATH modificado temporalmente para incluir: {specific_dir}")
    return shutil.which(binary_name) is not None

def convert_image_to_heic(input_path, output_path, quality, original_exif=None):
    _debug_print(f"Convirtiendo imagen: {os.path.basename(input_path)} a {os.path.basename(output_path)}")
    try:
        img = Image.open(input_path)
        if img.mode not in ('RGB', 'RGBA', 'L'):
            img = img.convert('RGB')
        elif img.mode == 'P': 
            img = img.convert('RGB')

        img.save(output_path, format="HEIF", quality=quality, exif=original_exif)
        _debug_print(f"Imagen {os.path.basename(input_path)} guardada exitosamente.")
        return True
    except Exception as e:
        print(f"\n     ❌ Error al convertir imagen {os.path.basename(input_path)}: {e}")
        return False

def convert_video_to_hevc(input_path, output_path, crf, preset, enable_gpu, gpu_encoder):
    encoder_option = "x265"

    if enable_gpu and gpu_encoder:
        encoder_option = gpu_encoder
    elif enable_gpu and not gpu_encoder:
        print(f"\n     ⚠️ Advertencia: Aceleración por GPU está habilitada pero no se ha especificado ENCODER_GPU. Usando CPU (x265) para {os.path.basename(input_path)}.")

    command = [
        "HandBrakeCLI",
        "-i", input_path,
        "-o", output_path,
        "-e", encoder_option,
        "-q", str(crf),
        "--all-audio",
        "--all-subtitles",
    ]
    if preset and encoder_option == "x265": 
        command.extend(["--preset", preset])

    creation_flags = 0
    if platform.system() == "Windows":
        creation_flags = subprocess.CREATE_NO_WINDOW

    _debug_print(f"Intentando convertir video: {os.path.basename(input_path)}")
    _debug_print(f"Comando HandBrakeCLI: {' '.join(command)}")

    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, creationflags=creation_flags)

        _debug_print(f"HandBrakeCLI STDOUT para {os.path.basename(input_path)}:\n{result.stdout.strip()}")
        _debug_print(f"HandBrakeCLI STDERR para {os.path.basename(input_path)}:\n{result.stderr.strip()}")

        if result.returncode == 0:
            return True
        else:
            if result.stderr:
                print(f"         STDERR de HandBrakeCLI:\n{result.stderr.strip()}")
                if "No such file or directory" in result.stderr or "Unable to open input file" in result.stderr:
                    print("         Sugerencia: El archivo de entrada no se encontró, no pudo ser abierto por HandBrakeCLI, o la ruta es incorrecta.")
                if "encoder initialization failed" in result.stderr or "No matching encoder" in result.stderr:
                    print(f"         Sugerencia: Problema con el codificador '{encoder_option}'. Revisa si HandBrakeCLI soporta este codificador en tu sistema (especialmente para GPU) o si los drivers de la GPU están bien configurados.")
                if "Invalid argument" in result.stderr or "Unknown option" in result.stderr:
                    print("         Sugerencia: Revisa los parámetros del comando de HandBrakeCLI. Puede haber una opción incorrecta o incompatible.")
            else:
                print("         No hay salida de error detallada de HandBrakeCLI (STDERR está vacío).")
            return False
    except FileNotFoundError:
        print("\n     ❌ Error: HandBrakeCLI no encontrado. Asegúrate de que esté instalado y en tu PATH o en la carpeta 'extra'.")
        _debug_print(f"PATH actual: {os.environ.get('PATH')}")
        return False
    except Exception as e:
        print(f"\n     ❌ Error inesperado al convertir video {os.path.basename(input_path)}: {e}")
        if "WinError 740" in str(e) or "requiere elevacion" in str(e):
            print("         Este error indica que HandBrakeCLI necesita permisos de administrador. Intenta ejecutar el script como administrador.")
        return False

def copy_metadata_with_exiftool(source_path, target_path, max_retries, retry_delay, new_modification_date_timestamp=None):
    _debug_print(f"Intentando copiar metadatos de {os.path.basename(source_path)} a {os.path.basename(target_path)}")

    for attempt in range(max_retries):
        try:
            time.sleep(0.1) 

            if not os.path.exists(target_path) or os.path.getsize(target_path) == 0:
                if attempt < max_retries - 1:
                    original_stdout.write(f"\r     ⚠️ ExifTool: El archivo de destino {os.path.basename(target_path)} no está listo para metadatos (intento {attempt + 1}/{max_retries}). Reintentando...")
                    original_stdout.flush()
                    time.sleep(retry_delay)
                    continue
                else:
                    print(f"\n     ❌ ExifTool: El archivo de destino {os.path.basename(target_path)} no existe o está vacío después de varios intentos. No se pudieron copiar metadatos.")
                    return False

            command = ["exiftool", "-TagsFromFile", source_path, "-all:all", "-overwrite_original", "-P"]

            if new_modification_date_timestamp:
                dt_object = datetime.datetime.fromtimestamp(new_modification_date_timestamp)
                exiftool_date_format = dt_object.strftime("%Y:%m:%d %H:%M:%S")
                command.extend(["-FileModifyDate=" + exiftool_date_format, "-FileCreateDate=" + exiftool_date_format])
                _debug_print(f"Estableciendo fecha de modificacion del archivo a: {exiftool_date_format}")

            command.append(target_path)

            _debug_print(f"Comando ExifTool: {' '.join(command)}")

            result = subprocess.run(command, capture_output=True, text=True, check=False)

            _debug_print(f"ExifTool STDOUT para {os.path.basename(target_path)}:\n{result.stdout.strip()}")
            _debug_print(f"ExifTool STDERR para {os.path.basename(target_path)}:\n{result.stderr.strip()}")

            if result.returncode == 0:
                return True
            else:
                print(f"\n     ❌ Error ExifTool al copiar metadatos a {os.path.basename(target_path)}:")
                print(f"         STDOUT: {result.stdout.strip()}")
                print(f"         STDERR: {result.stderr.strip()}")
                return False
        except FileNotFoundError:
            print("\n     ❌ Error: ExifTool no encontrado. Asegúrate de que esté instalado y en tu PATH o en la carpeta 'extra'.")
            _debug_print(f"PATH actual: {os.environ.get('PATH')}")
            return False
        except Exception as e:
            print(f"\n     ❌ Error inesperado con ExifTool en {os.path.basename(target_path)}: {e}")
            return False
    return False

def process_file_task(input_path, output_directory, heic_quality, hevc_crf, hevc_preset, enable_gpu_accel, gpu_encoder_name, max_retries, retry_delay):
    relative_path = os.path.relpath(input_path, SOURCE_DIRECTORY)
    output_subdir = os.path.join(output_directory, os.path.dirname(relative_path))
    os.makedirs(output_subdir, exist_ok=True)

    name, ext = os.path.splitext(os.path.basename(input_path))
    ext_lower = ext.lower()

    conversion_successful_tool = False
    final_processing_successful = False
    original_exif_data = None
    output_path = None
    original_size = 0 

    try:
        original_size = os.path.getsize(input_path)
    except FileNotFoundError:
        print(f"\n     ❌ Archivo no encontrado al intentar obtener el tamaño: {os.path.basename(input_path)}")
        return "failed_not_found", os.path.basename(input_path), original_size
    except Exception as e:
        print(f"\n     ❌ Error al obtener el tamaño del archivo {os.path.basename(input_path)}: {e}")
        return "failed_size_retrieval", os.path.basename(input_path), original_size

    if ext_lower in IMAGE_EXTENSIONS:
        output_filename = f"{name}.heic"
        output_path = os.path.join(output_subdir, output_filename)

        is_example_photo = DEVELOPER_MODE and os.path.commonpath([input_path, os.path.join(BASE_DIRECTORY, "extra", "archivos-ejemplo")]) == os.path.join(BASE_DIRECTORY, "extra", "archivos-ejemplo")

        if os.path.exists(output_path) and os.path.getmtime(output_path) > os.path.getmtime(input_path):
            if not is_example_photo:
                return "skipped_already_processed", os.path.basename(input_path), original_size
        # Si es foto de ejemplo en modo desarrollador, siempre procesa
        try:
            img = Image.open(input_path)
            if 'exif' in img.info:
                original_exif_data = img.info['exif']
            img.close()
        except Exception as e: 
            _debug_print(f"No se pudo leer EXIF de {os.path.basename(input_path)}: {e}")

        conversion_successful_tool = convert_image_to_heic(input_path, output_path, heic_quality, original_exif_data)

    elif ext_lower in VIDEO_EXTENSIONS:
        output_filename = f"{name}.mp4" 
        output_path = os.path.join(output_subdir, output_filename)

        if os.path.exists(output_path) and os.path.getmtime(output_path) > os.path.getmtime(input_path):
            return "skipped_already_processed", os.path.basename(input_path), original_size

        conversion_successful_tool = convert_video_to_hevc(input_path, output_path, hevc_crf, hevc_preset, enable_gpu_accel, gpu_encoder_name)

    else:
        return "skipped_unsupported", os.path.basename(input_path), original_size

    if conversion_successful_tool and output_path and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        _debug_print(f"Archivo de salida {os.path.basename(output_path)} existe y no está vacío.")

        new_mod_date_timestamp = None
        if ext_lower in VIDEO_EXTENSIONS:
            match = re.search(r'(\d{8})', name)
            if match:
                date_str = match.group(1)
                try:
                    dt_object = datetime.datetime.strptime(date_str, "%Y%m%d")

                    dt_object = dt_object.replace(hour=0, minute=0, second=0, microsecond=0)
                    new_mod_date_timestamp = dt_object.timestamp()
                    _debug_print(f"Fecha de modificación detectada en el nombre del video: {date_str}. Estableciendo a: {dt_object}")
                except ValueError:
                    _debug_print(f"Formato de fecha '{date_str}' en el nombre no es 'yyyymmdd' válido. Ignorando.")
            else:
                _debug_print("No se detectó el formato de fecha 'yyyymmdd' en el nombre del video. Dejando la fecha de modificación por defecto.")

        copy_metadata_successful = copy_metadata_with_exiftool(input_path, output_path, max_retries, retry_delay, new_mod_date_timestamp)
        if not copy_metadata_successful:
            print(f"\n     ⚠️ Advertencia: No se pudieron copiar todos los metadatos para {os.path.basename(input_path)}. El archivo convertido se mantiene.")

        try:
            if new_mod_date_timestamp:
                os.utime(output_path, (new_mod_date_timestamp, new_mod_date_timestamp))
                _debug_print(f"Fecha de modificación del sistema establecida desde el nombre para {os.path.basename(output_path)}.")
            else:
                original_stat = os.stat(input_path)
                file_ready_for_utime = False
                for attempt in range(max_retries):
                    if output_path and os.path.exists(output_path) and os.path.getsize(output_path) > 0: 
                        os.utime(output_path, (original_stat.st_atime, original_stat.st_mtime))
                        file_ready_for_utime = True
                        _debug_print(f"Fecha de modificación copiada para {os.path.basename(output_path)}.")
                        break
                    else:
                        _debug_print(f"Archivo de salida {os.path.basename(output_path)} no listo (intento {attempt + 1}/{max_retries}), reintentando utime...")
                        time.sleep(retry_delay)

                if not file_ready_for_utime:
                    print(f"\n     ⚠️ Advertencia: Archivo de salida no encontrado o vacío en {output_path} después de reintentos para copiar fecha. No se pudo establecer la fecha de modificación.")

            final_processing_successful = True

        except Exception as e:
            print(f"\n     ❌ Error en la gestión (copia de fecha o borrado) de archivos para {os.path.basename(input_path)}: {e}")
            final_processing_successful = False

    else:
        print(f"\n     ❌ Conversión fallida para {os.path.basename(input_path)}: La herramienta de conversión reportó un fallo o el archivo de salida no fue creado/está vacío.")
        final_processing_successful = False

    if final_processing_successful:
        try:
            # No borrar fotos de ejemplo si está activado el modo desarrollador
            if DEVELOPER_MODE and os.path.commonpath([input_path, os.path.join(BASE_DIRECTORY, "extra", "archivos-ejemplo")]) == os.path.join(BASE_DIRECTORY, "extra", "archivos-ejemplo"):
                _debug_print(f"Modo desarrollador activo: no se elimina {os.path.basename(input_path)} (foto de ejemplo).")
                return "processed", os.path.basename(input_path), original_size
            os.remove(input_path)
            _debug_print(f"Archivo original {os.path.basename(input_path)} eliminado tras conversion exitosa.")
            return "processed", os.path.basename(input_path), original_size
        except Exception as e:
            print(f"\n     ❌ Error al eliminar el archivo original {os.path.basename(input_path)}: {e}")
            return "failed_delete_original", os.path.basename(input_path), original_size
    else:
        return "failed_conversion", os.path.basename(input_path), original_size

def print_progress(total, processed, skipped_processed, skipped_unsupported, failed, phase_name, first_progress=False):
    completed = processed + skipped_processed + skipped_unsupported + failed
    percentage = (completed / total) * 100 if total > 0 else 0
    bar_length = 30
    filled_length = int(bar_length * percentage // 100)
    bar = '█' * filled_length + '░' * (bar_length - filled_length)
    progress_line = f"🖼️ {phase_name}: |{bar}| {percentage:.1f}% ({completed}/{total}) ⏳"
    if first_progress:
        # Borra la línea anterior (Procesando Fotos/Videos)
        sys.stdout.write('\r' + ' ' * 120 + '\r')
    sys.stdout.write(progress_line + ' ' * 10 + '\r')
    sys.stdout.flush()

def clear_progress_lines():
    sys.stdout.write('\r' + ' ' * 120 + '\r')
    sys.stdout.write(' ' * 120 + '\r')
    sys.stdout.flush()

def print_fotos_procesadas():
    clear_progress_lines()
    print("✅ Fotos procesadas")

def print_final_dashboard_and_summary(total_original_folder_size, num_image_files, num_video_files, dashboard_line, final_output_size):
    clear_console()
    print("="*60)
    print("🗂️  NEU (Necesito Espacio Urgente)")
    print(f"📸 Imagenes: {num_image_files} | 🎞️  Videos: {num_video_files}")
    print("="*60)
    print("🎯 PROCESO COMPLETADO")
    print("✅ YA PUEDE CERRAR EL PROGRAMA")
    if total_original_folder_size > 0:
        ahorro = total_original_folder_size - final_output_size
        porcentaje = ((total_original_folder_size - final_output_size) / total_original_folder_size) * 100 if total_original_folder_size > final_output_size else 0
        print("\a", end="")  # Beep de notificación
        print(f"🏆 Tamaño original: {get_human_readable_size(total_original_folder_size)} | Tamaño final: {get_human_readable_size(final_output_size)} | Espacio Ahorrado: {get_human_readable_size(ahorro)} ({porcentaje:.2f}%)")
    else:
        print("No se pudieron calcular las estadísticas de ahorro de espacio.")

def get_directory_size(path):
    total_size = 0
    if not os.path.exists(path):
        return 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if not os.path.islink(fp):
                try:
                    total_size += os.path.getsize(fp)
                except Exception as e:
                    print(f"\n     ⚠️ No se pudo obtener el tamaño de {fp}: {e}")
    return total_size

def print_initial_stats(total_original_folder_size, num_image_files, num_video_files, num_unsupported_files):
    print("="*60)
    print("🗂️  NEU (Necesito Espacio Urgente)")
    print(f"📏 Tamaño Original: {get_human_readable_size(total_original_folder_size)} | 📸 Imagenes: {num_image_files} | 🎞️  Videos: {num_video_files}")
    print("="*60)

def process_gallery():
    global log_file_handle
    global original_stdout, original_stderr

    try:
        os.makedirs(os.path.join(BASE_DIRECTORY, "extra"), exist_ok=True)

        log_file_handle = open(LOG_FILENAME, "w", encoding="utf-8") 
        sys.stdout = CustomStream(original_stdout, log_file_handle)
        sys.stderr = CustomStream(original_stderr, log_file_handle)

        original_path = os.environ.get("PATH", "")

        os.environ["PATH"] = EXTERNAL_TOOLS_DIRECTORY + os.pathsep + original_path

        if not check_binary_exists_in_path_or_dir("HandBrakeCLI"):
            print("ERROR: HandBrakeCLI no encontrado en tu PATH ni en la carpeta 'extra'. Asegúrate de que esté instalado y accesible.")
            print("       Sin HandBrakeCLI, la conversión de video no funcionará.")
            os.environ["PATH"] = original_path 
            return
        if not check_binary_exists_in_path_or_dir("exiftool"):
            print("ERROR: exiftool no encontrado en tu PATH ni en la carpeta 'extra'. Asegúrate de que esté instalado y accesible.")
            print("       Sin exiftool, la copia de metadatos y fechas de modificación no funcionará correctamente.")
            os.environ["PATH"] = original_path 
            return

        if not os.path.exists(SOURCE_DIRECTORY):
            print(f"Error: El directorio de origen no existe: {SOURCE_DIRECTORY}")
            os.environ["PATH"] = original_path
            return

        all_files_categorized = []

        for root, _, files in os.walk(SOURCE_DIRECTORY):
            for filename in files:
                file_path = os.path.join(root, filename)
                ext_lower = os.path.splitext(filename)[1].lower()
                try:
                    file_size = os.path.getsize(file_path)
                    if ext_lower in IMAGE_EXTENSIONS:
                        all_files_categorized.append((file_path, "image", file_size))
                    elif ext_lower in VIDEO_EXTENSIONS:
                        all_files_categorized.append((file_path, "video", file_size))
                    else:
                        all_files_categorized.append((file_path, "unsupported", file_size)) 
                except Exception as e:
                    print(f"\n     ⚠️ No se pudo acceder al archivo {filename} ({file_path}): {e}")

        total_original_folder_size = get_directory_size(SOURCE_DIRECTORY) 

        image_files_to_process = [(f[0], f[2]) for f in all_files_categorized if f[1] == "image"]
        video_files_to_process = [(f[0], f[2]) for f in all_files_categorized if f[1] == "video"]
        unsupported_files = [(f[0], f[2]) for f in all_files_categorized if f[1] == "unsupported"]

        total_images = len(image_files_to_process)
        total_videos = len(video_files_to_process)
        total_unsupported = len(unsupported_files)

        print_initial_stats(total_original_folder_size, total_images, total_videos, total_unsupported)
        dashboard_line = f"📏 Tamaño Original: {get_human_readable_size(total_original_folder_size)} | 📸 Imagenes: {total_images} | 🎞️  Videos: {total_videos}"

        if not all_files_categorized:
            print("No se encontraron archivos de imagen o video soportados para procesar.")
            os.environ["PATH"] = original_path
            return

        overall_processed_count = 0
        overall_skipped_already_processed_count = 0
        overall_skipped_unsupported_count = 0
        overall_failed_count = 0

        if total_images > 0:
            processed_count_img = 0
            skipped_processed_count_img = 0
            skipped_unsupported_count_img = 0
            failed_count_img = 0
            first_progress = True
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                future_to_file = {
                    executor.submit(
                        process_file_task,
                        file_path,
                        OUTPUT_DIRECTORY,
                        HEIC_QUALITY,
                        HEVC_CRF,
                        HEVC_PRESET,
                        ENABLE_GPU_ACCELERATION,
                        ENCODER_GPU,
                        MAX_RETRIES_FILE_OPS,
                        RETRY_DELAY_FILE_OPS
                    ): (file_path, original_size)
                    for file_path, original_size in image_files_to_process
                }

                for future in concurrent.futures.as_completed(future_to_file):
                    file_path, original_size = future_to_file[future]
                    try:
                        status, original_filename, _ = future.result() 
                        if status == "processed":
                            processed_count_img += 1
                            overall_processed_count += 1
                        elif status == "skipped_already_processed":
                            skipped_processed_count_img += 1
                            overall_skipped_already_processed_count += 1
                        elif status == "skipped_unsupported":
                            skipped_unsupported_count_img += 1
                            overall_skipped_unsupported_count += 1
                        elif status.startswith("failed"):
                            failed_count_img += 1
                            overall_failed_count += 1
                    except Exception as exc:
                        print(f'\n     ❌ El archivo {os.path.basename(file_path)} generó una excepción inesperada: {exc}')
                        failed_count_img += 1
                        overall_failed_count += 1

                    print_progress(total_images, processed_count_img, skipped_processed_count_img, skipped_unsupported_count_img, failed_count_img, "Fotos", first_progress=first_progress)
                    first_progress = False
            print_fotos_procesadas()

        if total_videos > 0:
            print("🎬 Procesando Videos")
            processed_count_vid = 0
            skipped_processed_count_vid = 0
            skipped_unsupported_count_vid = 0
            failed_count_vid = 0
            first_progress = True
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                future_to_file = {
                    executor.submit(
                        process_file_task,
                        file_path,
                        OUTPUT_DIRECTORY,
                        HEIC_QUALITY,
                        HEVC_CRF,
                        HEVC_PRESET,
                        ENABLE_GPU_ACCELERATION,
                        ENCODER_GPU,
                        MAX_RETRIES_FILE_OPS,
                        RETRY_DELAY_FILE_OPS
                    ): (file_path, original_size)
                    for file_path, original_size in video_files_to_process
                }

                for future in concurrent.futures.as_completed(future_to_file):
                    file_path, original_size = future_to_file[future]
                    try:
                        status, original_filename, _ = future.result() 
                        if status == "processed":
                            processed_count_vid += 1
                            overall_processed_count += 1
                        elif status == "skipped_already_processed":
                            skipped_processed_count_vid += 1
                            overall_skipped_already_processed_count += 1
                        elif status == "skipped_unsupported":
                            skipped_unsupported_count_vid += 1
                            overall_skipped_unsupported_count += 1
                        elif status.startswith("failed"):
                            failed_count_vid += 1
                            overall_failed_count += 1
                    except Exception as exc:
                        print(f'\n     ❌ El archivo {os.path.basename(file_path)} generó una excepción inesperada: {exc}')
                        failed_count_vid += 1
                        overall_failed_count += 1

                    print_progress(total_videos, processed_count_vid, skipped_processed_count_vid, skipped_unsupported_count_vid, failed_count_vid, "Videos", first_progress=first_progress)
                    first_progress = False
            clear_progress_lines()
            print(f"--- 🎞️  Videos terminados. Completadas: {processed_count_vid}, Saltadas (ya procesadas): {skipped_processed_count_vid}, Errores: {failed_count_vid} ---")

        if total_unsupported > 0:
            print("\n--- 🚫 Archivos Ignorados (Extensión No Soportada) ---")
            for file_path, _ in unsupported_files:
                print(f"     - {os.path.basename(file_path)}")
                overall_skipped_unsupported_count += 1
            print(f"--- Total de Archivos Ignorados: {total_unsupported} ---")

        final_output_size = get_directory_size(OUTPUT_DIRECTORY)
        print_final_dashboard_and_summary(
            total_original_folder_size,
            total_images,
            total_videos,
            dashboard_line,
            final_output_size
        )

    except Exception as main_e:
        print(f"\n\n🚨 ¡HA OCURRIDO UN ERROR CRÍTICO EN EL PROGRAMA PRINCIPAL! 🚨")
        print(f"Detalles del error: {main_e}")
        print(f"Por favor, revisa el archivo de registro '{LOG_FILENAME}' para más detalles.")
    finally:
        if log_file_handle:
            log_file_handle.close()
        sys.stdout = original_stdout 
        sys.stderr = original_stderr 

        os.environ["PATH"] = original_path

if __name__ == "__main__":
    try:
        process_gallery()
    except Exception as e:
        import traceback
        print("\n\n🚨 ERROR CRÍTICO 🚨\n", e)
        traceback.print_exc()
        input("\nPresiona ENTER para salir...")
    else:
        input("\nPresiona ENTER para salir...")