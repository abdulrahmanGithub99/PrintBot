"""واجهة Qt: أيقونة النظام + نافذة التحكم + الإعدادات + الطابعات + معالج الإعداد الأول."""
import json
import os
import time
from datetime import datetime

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QSystemTrayIcon,
    QMenu,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QDialog,
    QFormLayout,
    QLineEdit,
    QCheckBox,
    QComboBox,
    QMessageBox,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QHeaderView,
    QAbstractItemView,
    QTextBrowser,
)

from app import strings as S
from app.config import logs_dir, default_sumatra_path, default_icon_path
from app.printers import list_printers
from app.autostart import set_autostart, autostart_command
from app.bot_runner import BotRunner
from app.config import Config
import print_utils


def make_icon() -> QIcon:
    ico = default_icon_path()
    if ico:
        return QIcon(ico)
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#1a73e8"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 14, 14)
    p.setPen(QColor("white"))
    f = QFont()
    f.setBold(True)
    f.setPixelSize(36)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, "P")
    p.end()
    return QIcon(pm)


class Bridge(QObject):
    """جسر آمن بين خيط البوت وخيط الواجهة (الإشارات تعمل بشكل آمن عبر الخيوط)."""
    log = Signal(object)
    status = Signal(str, str)
    chat = Signal(int, str)


class LogStore:
    """كتابة السجل في ملف يومي مع حذف الملفات الأقدم من 30 يوماً."""
    RETENTION_DAYS = 30

    def __init__(self, dir_path: str):
        self.dir = dir_path
        os.makedirs(self.dir, exist_ok=True)

    def _path(self) -> str:
        return os.path.join(self.dir, datetime.now().strftime("bot_%Y%m%d.log"))

    def write(self, entry: dict) -> None:
        self._rotate()
        try:
            with open(self._path(), "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _rotate(self) -> None:
        cutoff = time.time() - self.RETENTION_DAYS * 86400
        try:
            for name in os.listdir(self.dir):
                fp = os.path.join(self.dir, name)
                if os.path.isfile(fp) and os.path.getmtime(fp) < cutoff:
                    try:
                        os.remove(fp)
                    except OSError:
                        pass
        except OSError:
            pass


class MainWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setWindowTitle(S.WINDOW_TITLE)
        self.setWindowIcon(make_icon())
        self.resize(720, 480)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # شريط الحالة العلوي
        top = QHBoxLayout()
        self.status_label = QLabel(S.STATUS_STOPPED)
        self.status_label.setStyleSheet("font-weight: bold; color: #888;")
        top.addWidget(self.status_label)
        top.addStretch(1)

        self.toggle_btn = QPushButton(S.BTN_TOGGLE_START)
        self.toggle_btn.clicked.connect(self.controller.toggle_bot)
        top.addWidget(self.toggle_btn)

        self.settings_btn = QPushButton(S.BTN_SETTINGS)
        self.settings_btn.clicked.connect(self.controller.open_settings)
        top.addWidget(self.settings_btn)

        self.printers_btn = QPushButton(S.BTN_PRINTERS)
        self.printers_btn.clicked.connect(self.controller.open_printers)
        top.addWidget(self.printers_btn)

        self.help_btn = QPushButton(S.BTN_HELP)
        self.help_btn.clicked.connect(self.controller.show_help)
        top.addWidget(self.help_btn)

        layout.addLayout(top)

        layout.addWidget(QLabel(S.HISTORY_TITLE))

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            [S.COL_TIME, S.COL_FILE, S.COL_PRINTER, S.COL_COPIES, S.COL_PAPER, S.COL_RESULT]
        )
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

    def add_log_entry(self, entry: dict):
        row = self.table.rowCount()
        self.table.insertRow(row)

        items = [
            QTableWidgetItem(str(entry.get("time", ""))),
            QTableWidgetItem(str(entry.get("file", ""))),
            QTableWidgetItem(str(entry.get("printer", ""))),
            QTableWidgetItem(str(entry.get("copies", ""))),
            QTableWidgetItem(str(entry.get("paper", ""))),
        ]
        for col, it in enumerate(items):
            self.table.setItem(row, col, it)

        result = entry.get("result", "")
        if result == "ok":
            text, color = S.RESULT_OK, "#1a7f37"
        elif result == "fail":
            text, color = S.RESULT_FAIL, "#c62828"
        else:
            text, color = str(result), "#888"
        result_item = QTableWidgetItem(text)
        result_item.setForeground(QColor(color))
        self.table.setItem(row, 5, result_item)
        self.table.scrollToBottom()

    def set_status(self, state: str, detail: str = ""):
        if state == "running":
            self.status_label.setText(S.STATUS_RUNNING)
            self.status_label.setStyleSheet("font-weight: bold; color: #1a7f37;")
            self.toggle_btn.setText(S.BTN_TOGGLE_STOP)
        elif state == "error":
            self.status_label.setText(S.STATUS_ERROR + (f": {detail}" if detail else ""))
            self.status_label.setStyleSheet("font-weight: bold; color: #c62828;")
            self.toggle_btn.setText(S.BTN_TOGGLE_START)
        elif state == "conflict":
            self.status_label.setText(detail or S.STATUS_CONFLICT)
            self.status_label.setStyleSheet("font-weight: bold; color: #c62828;")
            self.toggle_btn.setText(S.BTN_TOGGLE_START)
        else:
            self.status_label.setText(S.STATUS_STOPPED)
            self.status_label.setStyleSheet("font-weight: bold; color: #888;")
            self.toggle_btn.setText(S.BTN_TOGGLE_START)

    def closeEvent(self, event):
        event.ignore()
        self.hide()


class SettingsDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.config = controller.config
        self.setWindowTitle(S.SETTINGS_TITLE)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.token_edit = QLineEdit(self.config.bot_token)
        self.token_edit.setPlaceholderText("123456789:ABCdefGhIJKlmNoPQRstuVWxyZ")
        form.addRow(S.LBL_TOKEN, self.token_edit)

        self.users_list = QListWidget()
        self._reload_users()
        form.addRow(S.LBL_CHAT_ID, self.users_list)

        add_row = QHBoxLayout()
        self.manual_id_edit = QLineEdit()
        self.manual_id_edit.setPlaceholderText(S.PH_MANUAL_CHAT_ID)
        self.add_user_btn = QPushButton(S.BTN_ADD)
        self.add_user_btn.clicked.connect(self._add_user)
        add_row.addWidget(self.manual_id_edit, 1)
        add_row.addWidget(self.add_user_btn)
        form.addRow("", add_row)

        rm_row = QHBoxLayout()
        self.remove_user_btn = QPushButton(S.BTN_REMOVE_USER)
        self.remove_user_btn.clicked.connect(self._remove_user)
        self.clear_users_btn = QPushButton(S.BTN_UNAUTHORIZE)
        self.clear_users_btn.clicked.connect(self._clear_users)
        rm_row.addWidget(self.remove_user_btn)
        rm_row.addWidget(self.clear_users_btn)
        form.addRow("", rm_row)

        self.sumatra_edit = QLineEdit(self.config.sumatra_path or default_sumatra_path())
        form.addRow(S.LBL_SUMATRA, self.sumatra_edit)

        self.autostart_check = QCheckBox(S.LBL_AUTOSTART)
        self.autostart_check.setChecked(self.config.auto_start)
        form.addRow(self.autostart_check)

        layout.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(S.BTN_CANCEL)
        cancel.clicked.connect(self.reject)
        save = QPushButton(S.BTN_SAVE)
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _reload_users(self):
        self.users_list.clear()
        for cid in self.config.allowed_chat_ids:
            self.users_list.addItem(str(cid))

    def _add_user(self):
        text = self.manual_id_edit.text().strip()
        if not text.isdigit():
            QMessageBox.warning(self, S.SETTINGS_TITLE, S.MSG_INVALID_CHAT_ID)
            return
        if self.config.add_allowed_chat_id(int(text)):
            self.manual_id_edit.clear()
            self._reload_users()

    def _remove_user(self):
        item = self.users_list.currentItem()
        if item:
            self.config.remove_allowed_chat_id(int(item.text()))
            self._reload_users()

    def _clear_users(self):
        self.config.clear_allowed_chat_ids()
        self._reload_users()

    def _save(self):
        token = self.token_edit.text().strip()
        if token:
            self.config.bot_token = token
        self.config.sumatra_path = self.sumatra_edit.text().strip()
        self.config.auto_start = self.autostart_check.isChecked()
        self.config.save()
        set_autostart(self.config.auto_start)
        self.accept()
        self.controller.on_config_changed()


class AddPrinterDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(S.ADD_PRINTER_TITLE)
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.pick_combo = QComboBox()
        self.pick_combo.addItem("")
        for name in list_printers():
            self.pick_combo.addItem(name)
        form.addRow(S.LBL_PRINTER_PICK, self.pick_combo)

        self.manual_edit = QLineEdit()
        self.manual_edit.setPlaceholderText("اسم الطابعة كما يظهر في ويندوز")
        form.addRow(S.LBL_PRINTER_MANUAL, self.manual_edit)

        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("مثال: طابعة المنزل")
        form.addRow(S.LBL_PRINTER_LABEL, self.label_edit)

        layout.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(S.BTN_CANCEL)
        cancel.clicked.connect(self.reject)
        ok = QPushButton(S.BTN_OK)
        ok.clicked.connect(self._ok)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

    def printer_name(self) -> str:
        picked = self.pick_combo.currentText().strip()
        return picked or self.manual_edit.text().strip()

    def printer_label(self) -> str:
        return self.label_edit.text().strip()

    def _ok(self):
        if not self.printer_name():
            QMessageBox.warning(self, S.ADD_PRINTER_TITLE, "أدخل اسم الطابعة أولاً.")
            return
        self.accept()


class PrintersDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.config = controller.config
        self.setWindowTitle(S.PRINTERS_TITLE)
        self.setMinimumSize(460, 320)

        layout = QVBoxLayout(self)
        self.list = QListWidget()
        layout.addWidget(self.list)

        buttons = QHBoxLayout()
        add_btn = QPushButton(S.BTN_ADD_PRINTER)
        add_btn.clicked.connect(self._add)
        self.remove_btn = QPushButton(S.BTN_REMOVE_PRINTER)
        self.remove_btn.clicked.connect(self._remove)
        self.test_btn = QPushButton(S.BTN_TEST_PRINTER)
        self.test_btn.clicked.connect(self._test)
        self.default_btn = QPushButton(S.BTN_SET_DEFAULT)
        self.default_btn.clicked.connect(self._set_default)
        buttons.addWidget(add_btn)
        buttons.addWidget(self.remove_btn)
        buttons.addWidget(self.test_btn)
        buttons.addWidget(self.default_btn)
        layout.addLayout(buttons)

        close_btn = QPushButton("إغلاق")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self._reload()

    def _reload(self):
        self.list.clear()
        default_key = self.config.default.get("printer_key")
        for p in self.config.printers:
            text = p["label"]
            if p["id"] == default_key:
                text += S.DEFAULT_MARK
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, p["id"])
            self.list.addItem(item)

    def _selected_id(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _add(self):
        dlg = AddPrinterDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.config.add_printer(dlg.printer_name(), dlg.printer_label())
            self.config.save()
            self._reload()

    def _remove(self):
        pid = self._selected_id()
        if not pid:
            return
        label = self.config.printer_label(pid)
        ret = QMessageBox.question(
            self, S.PRINTERS_TITLE, S.MSG_CONFIRM_REMOVE.format(label=label),
            QMessageBox.Yes | QMessageBox.No,
        )
        if ret == QMessageBox.Yes:
            self.config.remove_printer(pid)
            self.config.save()
            self._reload()

    def _set_default(self):
        pid = self._selected_id()
        if pid:
            self.config.set_default(printer_key=pid)
            self.config.save()
            self._reload()

    def _test(self):
        pid = self._selected_id()
        if not pid:
            return
        self.test_btn.setEnabled(False)
        self.test_btn.setText(S.TESTING_PRINTER)
        QApplication.processEvents()
        try:
            print_utils.print_test_page(
                self.config.printer_name(pid), self.config.sumatra_path
            )
            QMessageBox.information(self, S.PRINTERS_TITLE, S.TEST_OK)
        except Exception as e:
            QMessageBox.warning(self, S.PRINTERS_TITLE, S.TEST_FAIL + str(e))
        finally:
            self.test_btn.setEnabled(True)
            self.test_btn.setText(S.BTN_TEST_PRINTER)


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(S.HELP_TITLE)
        self.resize(580, 540)

        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setPlainText(S.HELP_TEXT)
        browser.setOpenExternalLinks(False)
        layout.addWidget(browser)

        close_btn = QPushButton(S.BTN_CANCEL)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


class SetupWizard(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.config = controller.config
        self.bridge = controller.bridge
        self.detected_chat_id = None

        self.setWindowTitle(S.WIZARD_TITLE)
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        # الصفحة 1: التوكن
        page1 = QWidget()
        p1 = QVBoxLayout(page1)
        p1.addWidget(QLabel(S.WIZARD_STEP1))
        self.token_edit = QLineEdit(self.config.bot_token)
        self.token_edit.setPlaceholderText("123456789:ABCdefGhIJKlmNoPQRstuVWxyZ")
        p1.addWidget(self.token_edit)
        next_btn = QPushButton(S.WIZARD_NEXT)
        next_btn.clicked.connect(self._go_step2)
        p1.addWidget(next_btn)
        p1.addStretch(1)
        self.stack.addWidget(page1)

        # الصفحة 2: انتظار الاكتشاف
        page2 = QWidget()
        p2 = QVBoxLayout(page2)
        p2.addWidget(QLabel(S.WIZARD_STEP2))
        self.wait_label = QLabel(S.WIZARD_WAITING)
        p2.addWidget(self.wait_label)
        self.detected_label = QLabel("")
        self.detected_label.setStyleSheet("font-weight: bold; color: #1a7f37;")
        p2.addWidget(self.detected_label)
        self.authorize_btn = QPushButton(S.WIZARD_AUTHORIZE)
        self.authorize_btn.setEnabled(False)
        self.authorize_btn.clicked.connect(self._authorize)
        p2.addWidget(self.authorize_btn)
        self.manual_btn = QPushButton(S.WIZARD_MANUAL)
        self.manual_btn.clicked.connect(self._manual_entry)
        p2.addWidget(self.manual_btn)
        p2.addStretch(1)
        self.stack.addWidget(page2)

        # الصفحة 3: تم
        page3 = QWidget()
        p3 = QVBoxLayout(page3)
        done_title = QLabel(S.WIZARD_DONE_TITLE)
        done_title.setStyleSheet("font-weight: bold; font-size: 16px;")
        p3.addWidget(done_title)
        p3.addWidget(QLabel(S.WIZARD_DONE))
        finish_btn = QPushButton(S.WIZARD_FINISH)
        finish_btn.clicked.connect(self.accept)
        p3.addWidget(finish_btn)
        p3.addStretch(1)
        self.stack.addWidget(page3)

        self.bridge.chat.connect(self._on_chat)

    def _go_step2(self):
        token = self.token_edit.text().strip()
        if not token:
            QMessageBox.warning(self, S.WIZARD_TITLE, S.MSG_NEED_TOKEN)
            return
        self.config.bot_token = token
        self.config.save()
        self.controller.start_bot()
        self.stack.setCurrentIndex(1)

    def _on_chat(self, chat_id: int, name: str):
        self.detected_chat_id = chat_id
        self.detected_label.setText(
            S.WIZARD_DETECTED.format(chat_id=chat_id) + (f" ({name})" if name else "")
        )
        self.authorize_btn.setEnabled(True)

    def _authorize(self):
        if not self.detected_chat_id:
            return
        self.config.add_allowed_chat_id(self.detected_chat_id)
        self.config.save()
        self.stack.setCurrentIndex(2)

    def _manual_entry(self):
        text, ok = QInputDialog.getText(self, S.WIZARD_TITLE, S.WIZARD_MANUAL_PROMPT)
        if not (ok and text.strip().isdigit()):
            return
        self.config.add_allowed_chat_id(int(text.strip()))
        self.config.save()
        self.stack.setCurrentIndex(2)


class TrayApp(QObject):
    def __init__(self, app: QApplication, config: Config):
        super().__init__()
        self.app = app
        self.config = config

        self.bridge = Bridge()
        self.log_store = LogStore(logs_dir())
        self.runner = BotRunner(config, self.bridge)

        self._wizard_active = False

        # توصيل إشارات البوت بالواجهة
        self.bridge.log.connect(self._on_log)
        self.bridge.status.connect(self._on_status)
        self.bridge.chat.connect(self._on_chat_detected)

        # النافذة الرئيسية
        self.window = MainWindow(self)

        # أيقونة النظام
        self.tray = QSystemTrayIcon(make_icon(), self)
        self.tray.setToolTip(S.TRAY_TOOLTIP)
        self._build_menu()
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _build_menu(self):
        menu = QMenu()

        self.action_show = menu.addAction(S.MENU_SHOW)
        self.action_show.triggered.connect(self.show_window)

        menu.addSeparator()

        self.action_settings = menu.addAction(S.MENU_SETTINGS)
        self.action_settings.triggered.connect(self.open_settings)

        self.action_printers = menu.addAction(S.MENU_PRINTERS)
        self.action_printers.triggered.connect(self.open_printers)

        self.action_help = menu.addAction(S.MENU_HELP)
        self.action_help.triggered.connect(self.show_help)

        menu.addSeparator()

        self.action_toggle = menu.addAction(S.MENU_START)
        self.action_toggle.triggered.connect(self.toggle_bot)

        menu.addSeparator()

        self.action_about = menu.addAction(S.MENU_ABOUT)
        self.action_about.triggered.connect(self.show_about)

        menu.addSeparator()

        action_quit = menu.addAction(S.MENU_QUIT)
        action_quit.triggered.connect(self.quit)

        self.tray.setContextMenu(menu)

    # ---------- إجراءات ----------
    def show_window(self):
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def open_settings(self):
        SettingsDialog(self, self.window).exec()

    def open_printers(self):
        PrintersDialog(self, self.window).exec()

    def show_help(self):
        HelpDialog(self.window).exec()

    def show_about(self):
        QMessageBox.about(self.window, S.ABOUT_TITLE, S.ABOUT_TEXT)

    def toggle_bot(self):
        if self.runner.is_running:
            self.runner.stop()
        else:
            if not self.config.bot_token:
                QMessageBox.warning(self.window, S.SETTINGS_TITLE, S.MSG_NEED_TOKEN)
                self.open_settings()
                return
            self.start_bot()

    def start_bot(self):
        if self.config.bot_token:
            self.runner.start()

    def on_config_changed(self):
        # إذا تغيّر التوكن، أعد بناء حالة الواجهة
        self.window.set_status("stopped" if not self.runner.is_running else "running")

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.show_window()

    # ---------- استقبال إشارات البوت ----------
    def _on_log(self, entry: dict):
        self.log_store.write(entry)
        self.window.add_log_entry(entry)

    def _on_status(self, state: str, detail: str):
        self.window.set_status(state, detail)
        if state == "running":
            self.action_toggle.setText(S.MENU_STOP)
        else:
            self.action_toggle.setText(S.MENU_START)

    def _on_chat_detected(self, chat_id: int, name: str):
        if self._wizard_active:
            return
        ret = QMessageBox.question(
            self.window,
            "تفويض الحساب",
            f"تم استقبال رسالة من:\n{name}\nChat ID: {chat_id}\n\nهل تريد تفويض هذا الحساب؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if ret == QMessageBox.Yes:
            if self.config.add_allowed_chat_id(chat_id):
                self.config.save()

    def run_wizard(self):
        self._wizard_active = True
        wizard = SetupWizard(self, self.window)
        wizard.exec()
        self._wizard_active = False
        return wizard

    def quit(self):
        self.runner.stop()
        self.tray.hide()
        self.app.quit()
