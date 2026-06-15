import sys
import os
import ctypes
import logging

def resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

# Configure logging (only once!)
logging.basicConfig(
    level=logging.DEBUG,
    filename='app.log',
    filemode='w',
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# --- VLC library + plugin setup (ONLY ONCE, globally) ---
# Windows ships a bundled vlc/ folder; macOS/Linux fall back to a system VLC
# install (python-vlc locates it). Never hard-fail here — the app must launch
# even if VLC is absent (video playback is optional; detection/export don't need it).
vlc_path = resource_path('vlc')
_LIBVLC_NAME = {'win32': 'libvlc.dll', 'darwin': 'libvlc.dylib'}.get(sys.platform, 'libvlc.so')
libvlc_path = os.path.join(vlc_path, _LIBVLC_NAME)
plugins_path = os.path.join(vlc_path, 'plugins')
os.environ['PATH'] = vlc_path + os.pathsep + os.environ.get('PATH', '')
if os.path.isdir(plugins_path):
    os.environ['VLC_PLUGIN_PATH'] = plugins_path

try:
    if os.path.exists(libvlc_path):
        ctypes.CDLL(libvlc_path)
        logging.debug(f"Loaded bundled libvlc from {libvlc_path}")
except Exception as e:
    logging.error(f"Failed to preload bundled libvlc: {e}")

try:
    import vlc  # python-vlc; uses bundled or system libvlc
    VLC_AVAILABLE = True
except Exception as e:
    logging.error(f"python-vlc not available (is VLC installed?): {e}")
    vlc = None
    VLC_AVAILABLE = False

from PyQt5 import QtWidgets, QtGui
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtWidgets import (
    QFileDialog, QVBoxLayout, QHBoxLayout, QComboBox,
    QPushButton, QLabel, QWidget, QMessageBox
)

translations = {
    "jp": {
        "open_video": "ビデオを開く",
        "playback_speed": "再生速度:",
        "file_not_found": "ファイルが見つかりません",
        "select_file": "ビデオファイルを選択",
        "file_dialog_filter": "ビデオファイル (*.mp4 *.avi *.mov *.mkv)",
        "invalid_name": "新しいビデオ名は空にできません。",
        "invalid_chars": "ビデオ名に無効な文字が含まれています。",
        "file_exists": "同じ名前のファイルが既に存在します。",
        "success": "成功",
        "rename_success": "ビデオが正常にリネームされました。",
        "rename_error": "ビデオのリネームに失敗しました。",
        "frame_back": "前フレーム",
        "frame_forward": "次フレーム",
        "screenshot": "スクリーンショット",
        "screenshot_saved": "スクリーンショットを保存しました",
        "screenshot_failed": "スクリーンショットの保存に失敗しました",
        "save_screenshot": "スクリーンショットを保存",
    },
    "en": {
        "open_video": "Open Video",
        "playback_speed": "Playback Speed:",
        "file_not_found": "File not found",
        "select_file": "Select video file",
        "file_dialog_filter": "Video Files (*.mp4 *.avi *.mov *.mkv)",
        "invalid_name": "The new video name cannot be empty.",
        "invalid_chars": "The video name contains invalid characters.",
        "file_exists": "A file with that name already exists.",
        "success": "Success",
        "rename_success": "Video renamed successfully.",
        "rename_error": "Failed to rename video.",
        "frame_back": "Frame Back",
        "frame_forward": "Frame Forward",
        "screenshot": "Screenshot",
        "screenshot_saved": "Screenshot saved",
        "screenshot_failed": "Failed to save screenshot",
        "save_screenshot": "Save Screenshot",
    },
    "es": {
        "open_video": "Abrir video",
        "playback_speed": "Velocidad de reproducción:",
        "file_not_found": "Archivo no encontrado",
        "select_file": "Seleccionar archivo de video",
        "file_dialog_filter": "Archivos de video (*.mp4 *.avi *.mov *.mkv)",
        "invalid_name": "El nuevo nombre del video no puede estar vacío.",
        "invalid_chars": "El nombre del video contiene caracteres no válidos.",
        "file_exists": "Ya existe un archivo con ese nombre.",
        "success": "Éxito",
        "rename_success": "Video renombrado con éxito.",
        "rename_error": "Error al renombrar el video.",
        "frame_back": "Cuadro anterior",
        "frame_forward": "Cuadro siguiente",
        "screenshot": "Captura",
        "screenshot_saved": "Captura guardada",
        "screenshot_failed": "Error al guardar captura",
        "save_screenshot": "Guardar captura",
    },
    "kr": {
        "open_video": "비디오 열기",
        "playback_speed": "재생 속도:",
        "file_not_found": "파일을 찾을 수 없습니다",
        "select_file": "비디오 파일 선택",
        "file_dialog_filter": "비디오 파일 (*.mp4 *.avi *.mov *.mkv)",
        "invalid_name": "새 비디오 이름은 비워둘 수 없습니다.",
        "invalid_chars": "비디오 이름에 잘못된 문자가 포함되어 있습니다.",
        "file_exists": "해당 이름의 파일이 이미 존재합니다.",
        "success": "성공",
        "rename_success": "비디오 이름이 성공적으로 변경되었습니다.",
        "rename_error": "비디오 이름 변경 실패.",
        "frame_back": "이전 프레임",
        "frame_forward": "다음 프레임",
        "screenshot": "스크린샷",
        "screenshot_saved": "스크린샷 저장됨",
        "screenshot_failed": "스크린샷 저장 실패",
        "save_screenshot": "스크린샷 저장",
    },
    "cn": {
        "open_video": "打开视频",
        "playback_speed": "播放速度：",
        "file_not_found": "找不到文件",
        "select_file": "选择视频文件",
        "file_dialog_filter": "视频文件 (*.mp4 *.avi *.mov *.mkv)",
        "invalid_name": "新视频名称不能为空。",
        "invalid_chars": "视频名称包含无效字符。",
        "file_exists": "已有相同名称的文件存在。",
        "success": "成功",
        "rename_success": "视频重命名成功。",
        "rename_error": "视频重命名失败。",
        "frame_back": "上一帧",
        "frame_forward": "下一帧",
        "screenshot": "截图",
        "screenshot_saved": "截图已保存",
        "screenshot_failed": "截图保存失败",
        "save_screenshot": "保存截图",
    },
}


# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    filename='app.log',
    filemode='w',  # Overwrite previous logs
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class VideoPlayer(QtWidgets.QMainWindow):
    def __init__(self, language_code="en"):
        self.language_code = language_code
        self.trans = translations.get(self.language_code, translations["en"])
        super(VideoPlayer, self).__init__()
        self.setWindowTitle("Wild Player")
        self.setGeometry(100, 100, 800, 600)
        # Initialize rename_line_edit
        self.rename_line_edit = None
        try:
            # Determine the base path
            if getattr(sys, 'frozen', False):
                # If the application is bundled by PyInstaller
                base_path = sys._MEIPASS
                logging.debug("Running in a bundled executable.")
                logging.debug(base_path)
            else:
                # Running in development
                base_path = os.path.dirname(os.path.abspath(__file__))
                logging.debug("Running in development mode.")

                    # Path to the icon file
            icon_path = resource_path('assets/app_icon.ico')

            # Set the window icon
            self.setWindowIcon(QtGui.QIcon(icon_path))
            # Locate libvlc: prefer the bundled copy (Windows ships vlc/), else
            # rely on a system VLC install (macOS/Linux). Never sys.exit here —
            # raise so the caller keeps the app alive (video playback is optional).
            vlc_path = resource_path('vlc')
            libvlc_path = os.path.join(vlc_path, _LIBVLC_NAME)
            plugins_path = os.path.join(vlc_path, 'plugins')
            if os.path.exists(libvlc_path):
                try:
                    ctypes.cdll.LoadLibrary(libvlc_path)
                    os.environ['VLC_PLUGIN_PATH'] = plugins_path
                    logging.debug(f"Loaded bundled libvlc from {libvlc_path}")
                except Exception as e:
                    logging.error(f"Failed to load bundled libvlc: {e}")

            if not VLC_AVAILABLE or vlc is None:
                error_msg = ("VLC is not available. Install VLC from videolan.org "
                             "to use the video player.")
                QMessageBox.critical(self, "VLC not available", error_msg)
                raise RuntimeError(error_msg)

            # Initialize VLC instance (use bundled plugins if present, else system VLC)
            try:
                if os.path.isdir(plugins_path):
                    self.instance = vlc.Instance('--no-xlib', f'--plugin-path={plugins_path}')
                else:
                    self.instance = vlc.Instance('--no-xlib')
                if self.instance is None:
                    raise ValueError("vlc.Instance() returned None.")
                logging.debug("VLC Instance created successfully.")
            except Exception as e:
                error_msg = ("Could not start VLC. On macOS/Linux, install VLC from "
                             f"videolan.org to use the video player. ({e})")
                logging.error(error_msg)
                QMessageBox.critical(self, "VLC Initialization Error", error_msg)
                raise RuntimeError(error_msg)

            # Initialize media player
            try:
                self.media_player = self.instance.media_player_new()
                if self.media_player is None:
                    raise ValueError("Failed to create media player.")
                logging.debug("Media player initialized successfully.")
            except Exception as e:
                error_msg = f"Failed to create media player: {e}"
                logging.error(error_msg)
                QMessageBox.critical(
                    self,
                    "Media Player Initialization Error",
                    error_msg
                )
                raise RuntimeError(error_msg)

            self.current_folder = ""
            self.video_files = []
            self.current_video_index = -1

            # Set up UI components
            self.init_ui()

            # Handle command-line arguments
            if len(sys.argv) > 1:
                path_arg = sys.argv[1]
                if os.path.isfile(path_arg):
                    self.open_file(file_path=path_arg)
                elif os.path.isdir(path_arg):
                    # If it's a directory, open the file dialog starting at this directory
                    self.open_file(start_dir=path_arg)
                else:
                    logging.warning(f"Path does not exist: {path_arg}")
                    QtWidgets.QMessageBox.warning(
                        self,
                        "パスが存在しません",
                        f"指定されたパスは存在しません:\n{path_arg}"
                    )
            else:
                logging.debug("No command-line arguments provided.")

        except Exception as e:
            error_msg = f"An unexpected error occurred during initialization: {e}"
            logging.exception(error_msg)
            QMessageBox.critical(
                self,
                "Initialization Error",
                error_msg
            )
            input("Press Enter to exit.")
            sys.exit(1)

    def init_ui(self):
        # Video frame widget
        self.video_frame = QtWidgets.QFrame(self)
        self.setCentralWidget(self.video_frame)

        # --- Build a fixed-width controls bar, centered horizontally ---
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(4)
        controls_layout.setContentsMargins(0, 0, 0, 0)

        # Styles
        button_style = """
            QPushButton {
                background-color: white;
                color: black;
                border: 1px solid #ccc;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #f0f0f0;
                border-color: #999;
            }
        """
        icon_button_style = """
            QPushButton {
                background-color: white;
                border: none;
                padding: 8px;
            }
            QPushButton:hover {
                background-color: #f0f0f0;
                border-radius: 6px;
            }
        """

        # Open Button
        self.open_button = QPushButton(self.trans["open_video"])
        self.open_button.setStyleSheet(button_style)
        self.open_button.clicked.connect(self.open_file)
        self.open_button.setFixedSize(120, 50)
        controls_layout.addWidget(self.open_button)

        # Previous Button
        self.prev_button = QPushButton()
        self.prev_button.setIcon(QtGui.QIcon(resource_path("assets/prev_icon.png")))
        self.prev_button.setIconSize(QSize(32, 32))
        self.prev_button.setStyleSheet(icon_button_style)
        self.prev_button.clicked.connect(self.prev_video)
        self.prev_button.setFixedSize(50, 50)
        controls_layout.addWidget(self.prev_button)

        # Frame Back Button
        self.frame_back_button = QPushButton()
        self.frame_back_button.setIcon(QtGui.QIcon(resource_path("assets/frame_back.png")))
        self.frame_back_button.setIconSize(QSize(28, 28))
        self.frame_back_button.setToolTip(self.trans["frame_back"])
        self.frame_back_button.setStyleSheet(icon_button_style)
        self.frame_back_button.clicked.connect(self.frame_back)
        self.frame_back_button.setFixedSize(50, 50)
        controls_layout.addWidget(self.frame_back_button)

        # Play/Pause Button
        self.play_pause_button = QPushButton()
        self.play_pause_button.setIcon(QtGui.QIcon(resource_path("assets/pauseplay_icon.png")))
        self.play_pause_button.setIconSize(QSize(32, 32))
        self.play_pause_button.setStyleSheet(icon_button_style)
        self.play_pause_button.clicked.connect(self.play_pause)
        self.play_pause_button.setFixedSize(50, 50)
        controls_layout.addWidget(self.play_pause_button)

        # Frame Forward Button
        self.frame_fwd_button = QPushButton()
        self.frame_fwd_button.setIcon(QtGui.QIcon(resource_path("assets/frame_forward.png")))
        self.frame_fwd_button.setIconSize(QSize(28, 28))
        self.frame_fwd_button.setToolTip(self.trans["frame_forward"])
        self.frame_fwd_button.setStyleSheet(icon_button_style)
        self.frame_fwd_button.clicked.connect(self.frame_forward)
        self.frame_fwd_button.setFixedSize(50, 50)
        controls_layout.addWidget(self.frame_fwd_button)

        # Replay Button
        self.replay_button = QPushButton()
        self.replay_button.setIcon(QtGui.QIcon(resource_path("assets/replay_icon.png")))
        self.replay_button.setIconSize(QSize(32, 32))
        self.replay_button.setStyleSheet(icon_button_style)
        self.replay_button.clicked.connect(self.replay_video)
        self.replay_button.setFixedSize(50, 50)
        controls_layout.addWidget(self.replay_button)

        # Next Button
        self.next_button = QPushButton()
        self.next_button.setIcon(QtGui.QIcon(resource_path("assets/next_icon.png")))
        self.next_button.setIconSize(QSize(32, 32))
        self.next_button.setStyleSheet(icon_button_style)
        self.next_button.clicked.connect(self.next_video)
        self.next_button.setFixedSize(50, 50)
        controls_layout.addWidget(self.next_button)

        # Screenshot Button
        self.screenshot_button = QPushButton()
        self.screenshot_button.setIcon(QtGui.QIcon(resource_path("assets/save_frame.png")))
        self.screenshot_button.setIconSize(QSize(28, 28))
        self.screenshot_button.setToolTip(self.trans["screenshot"])
        self.screenshot_button.setStyleSheet(icon_button_style)
        self.screenshot_button.clicked.connect(self.save_screenshot)
        self.screenshot_button.setFixedSize(50, 50)
        controls_layout.addWidget(self.screenshot_button)

        # Speed Control Label
        self.speed_label = QLabel(self.trans["playback_speed"])
        self.speed_label.setAlignment(Qt.AlignCenter)
        self.speed_label.setFixedHeight(50)
        controls_layout.addWidget(self.speed_label)

        # Speed Control ComboBox
        self.speed_combo = QComboBox(self)
        self.speed_combo.setStyleSheet("""
            QComboBox {
                color: black;
                background-color: white;
            }
            QComboBox QAbstractItemView {
                background-color: black;
                color: white;
                selection-background-color: white;
                selection-color: black;
            }
        """)
        log_speeds = [1, 2, 4, 8, 16, 32]
        self.speed_combo.addItems([f"x{v}" for v in log_speeds])
        self.speed_combo.setCurrentText("x1")
        self.speed_combo.currentTextChanged.connect(self.change_speed)
        self.speed_combo.setFixedSize(70, 50)
        controls_layout.addWidget(self.speed_combo)

        # --- Fixed-width container for controls, centered in the window ---
        controls_widget = QWidget()
        controls_widget.setLayout(controls_layout)
        controls_widget.setSizePolicy(
            QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed
        )

        controls_center_layout = QHBoxLayout()
        controls_center_layout.setContentsMargins(0, 0, 0, 0)
        controls_center_layout.addStretch()
        controls_center_layout.addWidget(controls_widget)
        controls_center_layout.addStretch()

        # --- Rename bar (also fixed-width, centered) ---
        rename_layout = QHBoxLayout()
        rename_layout.setContentsMargins(0, 0, 0, 0)

        self.rename_line_edit = QtWidgets.QLineEdit(self)
        self.rename_line_edit.setStyleSheet("""
            QLineEdit {
                color: black;
                background-color: white;
                selection-color: white;
                selection-background-color: #0078D4;
            }
        """)
        self.rename_line_edit.setFixedHeight(30)
        rename_layout.addWidget(self.rename_line_edit)

        self.rename_line_edit.returnPressed.connect(self.rename_video)

        self.rename_button = QPushButton("OK")
        self.rename_button.setStyleSheet("color: black;")
        self.rename_button.clicked.connect(self.rename_video)
        self.rename_button.setFixedSize(50, 30)
        rename_layout.addWidget(self.rename_button)

        rename_widget = QWidget()
        rename_widget.setLayout(rename_layout)
        rename_widget.setSizePolicy(
            QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed
        )
        rename_widget.setFixedWidth(controls_widget.sizeHint().width())

        rename_center_layout = QHBoxLayout()
        rename_center_layout.setContentsMargins(0, 0, 0, 0)
        rename_center_layout.addStretch()
        rename_center_layout.addWidget(rename_widget)
        rename_center_layout.addStretch()

        # --- Main layout ---
        layout = QVBoxLayout()
        layout.addWidget(self.video_frame)
        layout.addLayout(controls_center_layout)
        layout.addLayout(rename_center_layout)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # Disable rename controls initially
        self.set_rename_controls_enabled(False)

        # VLC widget for video output
        if sys.platform == "darwin":
            self.media_player.set_nsobject(int(self.video_frame.winId()))
        elif sys.platform == "win32":
            self.media_player.set_hwnd(int(self.video_frame.winId()))
        else:
            self.media_player.set_xwindow(int(self.video_frame.winId()))

    def open_file(self, file_path=None, start_dir=""):
        if not file_path:
            if not start_dir:
                start_dir = ""
            file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.trans["select_file"],
            start_dir,
            self.trans["file_dialog_filter"]
        )
        if file_path:
            self.current_folder = os.path.dirname(file_path)
            self.load_videos_from_folder()
            normalized_file_path = os.path.normpath(file_path).lower()
            try:
                self.current_video_index = self.video_files.index(normalized_file_path)
                self.play_video()
            except ValueError:
                QtWidgets.QMessageBox.warning(
                self,
                self.trans["file_not_found"],
                f"{self.trans['file_not_found']}:\n{file_path}"
            )
        else:
            logging.debug("No file selected.")

    def load_videos_from_folder(self):
        # Get all video files in the folder, sorted alphabetically
        self.video_files = sorted(
            [
                os.path.normpath(os.path.join(self.current_folder, f)).lower()
                for f in os.listdir(self.current_folder)
                if f.lower().endswith((".mp4", ".avi", ".mov", ".mkv"))
            ]
        )
        logging.debug("Loaded video files: %s", self.video_files)  # Debugging statement

    def rename_video(self):
        if self.video_files and self.current_video_index >= 0:
            # Get the current video path
            old_video_path = self.video_files[self.current_video_index]
            old_dir = os.path.dirname(old_video_path)
            old_name = os.path.basename(old_video_path)
            old_base_name, old_ext = os.path.splitext(old_name)

            # Get the new name from the line edit
            new_base_name = self.rename_line_edit.text().strip()

            # Validate new name
            if not new_base_name:
                QtWidgets.QMessageBox.warning(self, self.trans["invalid_name"], self.trans["invalid_name"])
                return

            # Check for invalid characters
            if any(char in new_base_name for char in r'\/:*?"<>|'):
                QtWidgets.QMessageBox.warning(self, self.trans["invalid_chars"], self.trans["invalid_chars"])
                return

            # Construct new video path
            new_video_name = new_base_name + old_ext
            new_video_path = os.path.join(old_dir, new_video_name)

            # Check if a file with the new name already exists
            if os.path.exists(new_video_path):
                QtWidgets.QMessageBox.warning(self, self.trans["file_exists"], self.trans["file_exists"])
                return

            # Attempt to rename the file
            try:
                # Stop the media player
                self.media_player.stop()

                os.rename(old_video_path, new_video_path)
                logging.debug(f"Renamed video: {old_video_path} to {new_video_path}")

                # Update the video files list
                self.video_files[self.current_video_index] = new_video_path

                # Reload the video with the new path
                self.play_video()
                QtWidgets.QMessageBox.information(self, self.trans["success"], self.trans["rename_success"])
            except Exception as e:
                logging.error(f"Failed to rename video: {e}")
                QtWidgets.QMessageBox.critical(self, self.trans["rename_error"], f"{self.trans['rename_error']}: {e}")

    def set_rename_controls_enabled(self, enabled):
        self.rename_line_edit.setEnabled(enabled)
        self.rename_button.setEnabled(enabled)

    def play_video(self):
        if self.video_files and self.current_video_index >= 0:
            video_path = self.video_files[self.current_video_index]
            media = self.instance.media_new(video_path)
            self.media_player.set_media(media)
            self.media_player.play()

            # Update the window title with the video name
            video_name = os.path.basename(video_path)
            self.setWindowTitle(f"Wild Player - {video_name}")

            # Update the rename line edit with the current video name (without extension)
            base_name, _ = os.path.splitext(video_name)
            self.rename_line_edit.setText(base_name)

            # Enable rename controls
            self.set_rename_controls_enabled(True)

    def stop_video(self):
        self.media_player.stop()
        self.set_rename_controls_enabled(False)

    def play_pause(self):
        if self.media_player.is_playing():
            self.media_player.pause()
            logging.debug("Video paused")  # Debugging statement
        else:
            self.media_player.play()
            logging.debug("Video playing")  # Debugging statement

    def prev_video(self):
        if self.current_video_index > 0:
            self.current_video_index -= 1
            logging.debug(f"Switching to previous video: Index {self.current_video_index}")  # Debugging
            self.play_video()

    def next_video(self):
        if self.current_video_index < len(self.video_files) - 1:
            self.current_video_index += 1
            logging.debug(f"Switching to next video: Index {self.current_video_index}")  # Debugging
            self.play_video()

    def replay_video(self):
        logging.debug("Replay button clicked")  # Debugging statement
        if self.media_player.get_media():
            # Option 1: Stop and Play
            self.media_player.stop()
            self.media_player.play()
            logging.debug("Video replayed using stop() and play()")  # Debugging

    def frame_back(self):
        """Step one frame backward (only when paused)."""
        if self.media_player.is_playing():
            return
        fps = self.media_player.get_fps()
        if fps <= 0:
            fps = 30.0
        frame_ms = int(1000.0 / fps)
        current = self.media_player.get_time()
        new_time = max(0, current - frame_ms)
        self.media_player.set_time(new_time)
        logging.debug(f"Frame back: {current}ms -> {new_time}ms (fps={fps:.1f})")

    def frame_forward(self):
        """Step one frame forward (only when paused)."""
        if self.media_player.is_playing():
            return
        self.media_player.next_frame()
        logging.debug("Frame forward")

    def save_screenshot(self):
        """Save the current frame as an image file."""
        if self.media_player.is_playing():
            return
        if not self.media_player.get_media():
            return

        # Build default filename from video name + timestamp
        video_name = ""
        if self.video_files and self.current_video_index >= 0:
            video_name = os.path.splitext(
                os.path.basename(self.video_files[self.current_video_index])
            )[0]
        current_ms = self.media_player.get_time()
        default_name = f"{video_name}_frame_{current_ms}ms.png" if video_name else "screenshot.png"

        start_dir = self.current_folder if self.current_folder else ""
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            self.trans["save_screenshot"],
            os.path.join(start_dir, default_name),
            "PNG (*.png);;JPEG (*.jpg);;BMP (*.bmp)",
        )
        if not save_path:
            return

        # VLC snapshot: 0 = video output index, 0/0 = original resolution
        result = self.media_player.video_take_snapshot(0, save_path, 0, 0)
        if result == 0:
            logging.debug(f"Screenshot saved to {save_path}")
            QtWidgets.QMessageBox.information(
                self, self.trans["success"],
                f"{self.trans['screenshot_saved']}:\n{save_path}",
            )
        else:
            logging.error(f"Screenshot failed (VLC returned {result})")
            QtWidgets.QMessageBox.warning(
                self, self.trans["screenshot_failed"],
                self.trans["screenshot_failed"],
            )

    def change_speed(self, speed_text):
        speed = float(speed_text.replace("x", ""))  # Remove the "x"
        if self.media_player.is_playing():
            self.media_player.set_rate(speed)
            logging.debug(f"Playback speed changed to: {speed}x")
        else:
            self.media_player.set_rate(speed)
            self.media_player.play()
            logging.debug(f"Playback speed set to: {speed}x and video playing")


if __name__ == "__main__":
    try:
        app = QtWidgets.QApplication(sys.argv)
        icon_path = resource_path('assets/app_icon.ico')
        app.setWindowIcon(QtGui.QIcon(icon_path))
        player = VideoPlayer()
        player.show()
        sys.exit(app.exec_())
    except Exception as e:
        logging.exception("An unexpected error occurred: %s", e)
        input("Press Enter to exit.")

