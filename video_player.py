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

# --- VLC DLL and plugin setup (ONLY ONCE, globally) ---
vlc_path = resource_path('vlc')
libvlc_path = os.path.join(vlc_path, 'libvlc.dll')
plugins_path = os.path.join(vlc_path, 'plugins')
os.environ['PATH'] = vlc_path + os.pathsep + os.environ.get('PATH', '')
os.environ['VLC_PLUGIN_PATH'] = plugins_path

try:
    ctypes.CDLL(libvlc_path)
    logging.debug("Successfully loaded libvlc.dll")
except Exception as e:
    logging.error(f"Failed to load libvlc.dll: {e}")
    # Optionally: sys.exit(1)  # Uncomment if you want to hard-fail

import vlc  # <-- do this only after the above setup

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
            # Path to VLC directory
            vlc_path = resource_path('vlc')
            logging.debug(f"VLC path set to: {vlc_path}")

            # Path to libvlc.dll
            libvlc_path = os.path.join(vlc_path, 'libvlc.dll')
            logging.debug(f"libvlc.dll path set to: {libvlc_path}")

            # Check if libvlc.dll exists
            if not os.path.exists(libvlc_path):
                error_msg = f"libvlc.dll not found at {libvlc_path}. Please ensure the VLC directory is bundled correctly."
                logging.error(error_msg)
                QMessageBox.critical(
                    self,
                    "VLC DLL Not Found",
                    error_msg
                )
                sys.exit(1)

            # Load libvlc.dll using ctypes
            try:
                ctypes.cdll.LoadLibrary(libvlc_path)
                logging.debug(f"Successfully loaded libvlc.dll from {libvlc_path}")
            except Exception as e:
                error_msg = f"Failed to load libvlc.dll: {e}"
                logging.error(error_msg)
                QMessageBox.critical(
                    self,
                    "Failed to Load VLC DLL",
                    error_msg
                )
                sys.exit(1)

            # Set the VLC plugin path environment variable
            plugins_path = os.path.join(vlc_path, 'plugins')
            os.environ['VLC_PLUGIN_PATH'] = plugins_path
            logging.debug(f"VLC_PLUGIN_PATH set to: {plugins_path}")

            # Initialize VLC instance with the plugin path
            try:
                self.instance = vlc.Instance('--no-xlib', f'--plugin-path={plugins_path}')
                if self.instance is None:
                    raise ValueError("vlc.Instance() returned None.")
                logging.debug("VLC Instance created successfully.")
            except Exception as e:
                error_msg = f"Failed to create VLC Instance: {e}"
                logging.error(error_msg)
                QMessageBox.critical(
                    self,
                    "VLC Initialization Error",
                    error_msg
                )
                sys.exit(1)

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
                sys.exit(1)

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

        # Controls layout
        controls_layout = QHBoxLayout()

        # Unified modern style for all control buttons
        button_style = """
            QPushButton {
                background-color: white;
                color: black;
                border: 1px solid #ccc;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 30px;
            }
            QPushButton:hover {
                background-color: #f0f0f0;
                border-color: #999;
            }
        """
        # Open Button
        self.open_button = QPushButton(self.trans["open_video"])
        self.open_button.setStyleSheet(button_style)
        self.open_button.clicked.connect(self.open_file)
        self.open_button.setFixedHeight(50)
        controls_layout.addWidget(self.open_button)
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

        # Previous Button
        self.prev_button = QPushButton()
        self.prev_button.setIcon(QtGui.QIcon(resource_path("assets/prev_icon.png")))
        self.prev_button.setIconSize(QSize(32, 32))
        self.prev_button.setStyleSheet(icon_button_style)
        self.prev_button.clicked.connect(self.prev_video)
        self.prev_button.setFixedHeight(50)
        controls_layout.addWidget(self.prev_button)

        # Play/Pause Button
        self.play_pause_button = QPushButton()
        self.play_pause_button.setIcon(QtGui.QIcon(resource_path("assets/pauseplay_icon.png")))
        self.play_pause_button.setIconSize(QSize(32, 32))
        self.play_pause_button.setStyleSheet(icon_button_style)
        self.play_pause_button.clicked.connect(self.play_pause)
        self.play_pause_button.setFixedHeight(50)
        controls_layout.addWidget(self.play_pause_button)

        # Replay Button
        self.replay_button = QPushButton()
        self.replay_button.setIcon(QtGui.QIcon(resource_path("assets/replay_icon.png")))
        self.replay_button.setIconSize(QSize(32, 32))
        self.replay_button.setStyleSheet(icon_button_style)
        self.replay_button.clicked.connect(self.replay_video)
        self.replay_button.setFixedHeight(50)
        controls_layout.addWidget(self.replay_button)

        # Next Button
        self.next_button = QPushButton()
        self.next_button.setIcon(QtGui.QIcon(resource_path("assets/next_icon.png")))
        self.next_button.setIconSize(QSize(32, 32))
        self.next_button.setStyleSheet(icon_button_style)
        self.next_button.clicked.connect(self.next_video)
        self.next_button.setFixedHeight(50)
        controls_layout.addWidget(self.next_button)

        # Speed Control Label
        self.speed_label = QLabel(self.trans["playback_speed"])
        self.speed_label.setAlignment(Qt.AlignCenter)
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
        self.speed_combo.addItems([f"x{v}" for v in log_speeds])    # 1.0x to 20.0x
        self.speed_combo.setCurrentText("1.0")  # Default speed
        self.speed_combo.currentTextChanged.connect(self.change_speed)
        self.speed_combo.setFixedHeight(50)
        controls_layout.addWidget(self.speed_combo)


    # Main layout
        layout = QVBoxLayout()
        layout.addWidget(self.video_frame)
        layout.addLayout(controls_layout)

        # Rename controls layout
        rename_layout = QHBoxLayout()

        # Text field for entering new name
        self.rename_line_edit = QtWidgets.QLineEdit(self)
        self.rename_line_edit.setStyleSheet("""
            QLineEdit {
                color: black;
                background-color: white;
                selection-color: white;
                selection-background-color: #0078D4;
            }
        """)
        rename_layout.addWidget(self.rename_line_edit)

        # Connect returnPressed signal to rename_video method
        self.rename_line_edit.returnPressed.connect(self.rename_video) 

        # Rename button
        self.rename_button = QPushButton("OK")
        self.rename_button.setStyleSheet("color: black;")
        self.rename_button.clicked.connect(self.rename_video)
        rename_layout.addWidget(self.rename_button)

        # Adjust sizes and styles if necessary
        self.rename_button.setFixedHeight(30)
        self.rename_line_edit.setFixedHeight(30)

        # Add the rename_layout to the main layout
        layout.addLayout(rename_layout)

        # Container widget to apply layout
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
            self.setWindowTitle(f"DiegoMOV プレーヤー - {video_name}")

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

