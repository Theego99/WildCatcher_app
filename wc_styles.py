"""WildCatcher UI stylesheet constants."""

START_BUTTON_STYLE = """
    QPushButton { font-size: 18px; padding: 10px 20px; color: #FFFFFF; background-color: rgba(67, 120, 32, 0.4); border: 2px solid #437820; border-radius: 10px; }
    QPushButton:hover { background-color: rgba(67, 120, 32, 1); }
"""

STOP_BUTTON_STYLE = """
    QPushButton { font-size: 18px; padding: 10px 20px; color: #FFFFFF; background-color: rgba(180, 30, 30, 0.4); border: 2px solid #B41E1E; border-radius: 10px; }
    QPushButton:hover { background-color: rgba(180, 30, 30, 1); }
"""

DARK_MSGBOX_STYLE = """
    QMessageBox { background-color: #1E1E1E; color: #FFFFFF; }
    QLabel { color: #FFFFFF; }
    QPushButton { font-size: 16px; padding: 5px; border-radius: 5px; background-color: #3C3C3C; color: #FFFFFF; }
    QPushButton:hover { background-color: #2E2E2E; }
"""

SIDEBAR_BUTTON_STYLE = """
    QPushButton { border: none; }
    QPushButton:hover { background-color: #9bc472; border-radius: 5px; }
"""

BROWSE_BUTTON_STYLE = """
    QPushButton { font-size: 16px; color: #FFFFFF; background-color: #FF9800; border: none; padding: 10px; border-radius: 5px; }
    QPushButton:hover { background-color: #FB8C00; }
"""

IMPORT_BUTTON_STYLE = """
    QPushButton { background-color: #0078D4; color: #FFFFFF; font-size: 16px; padding: 10px; border-radius: 5px; }
    QPushButton:hover { background-color: #0056b3; }
"""

PROGRESS_BAR_STYLE = """
    QProgressBar { background-color: #3C3C3C; border: none; color: #FFFFFF; text-align: center; height: 30px; border-radius: 5px; }
    QProgressBar::chunk { background-color: #9bc472; border-radius: 5px; }
"""

LOG_TEXTEDIT_STYLE = """
    QTextEdit { background-color: #1E1E1E; color: #FFFFFF; border: 1px solid #3C3C3C; border-radius: 5px; font-size: 14px; }
"""

GLOBAL_MESSAGEBOX_STYLE = """
    QMessageBox { background-color: #1E1E1E; color: #FFFFFF; }
    QMessageBox QLabel { color: #FFFFFF; }
    QMessageBox QPushButton { background-color: #0078D4; color: #FFFFFF; border-radius: 5px; padding: 5px 10px; }
    QMessageBox QPushButton:hover { background-color: #0056b3; }
"""

# Dark, compact tooltips (default Qt tooltips render as a large white box).
TOOLTIP_STYLE = """
    QToolTip { color: #FFFFFF; background-color: #1E2E1E; border: 1px solid #3C5C3C; padding: 5px 7px; border-radius: 4px; font-size: 12px; }
"""

MODEL_CARD_STYLE = """
    QFrame { background-color: #1E2E1E; border: 1px solid #3C5C3C; border-radius: 6px; padding: 8px; }
    QFrame:hover { border-color: #9bc472; }
"""

PIPELINE_STEP_STYLE = """
    QFrame { background-color: #1E1E2E; border: 1px solid #3C3C5C; border-radius: 6px; padding: 8px; }
"""
