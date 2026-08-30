"""نقطة الدخول: واجهة Qt مع أيقونة النظام ومعالج الإعداد الأول."""
import os
import sys

# عند التشغيل من المصدر، أضف جذر المشروع إلى sys.path حتى تعمل استيرادات app.* والوحدات الجذرية
if not getattr(sys, "frozen", False):
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)

from PySide6.QtCore import Qt, QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox

from app.config import Config, lock_path, appdata_dir
from app.autostart import set_autostart
from app.tray_app import TrayApp


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("PrintBot")
    app.setLayoutDirection(Qt.RightToLeft)

    # منع تشغيل أكثر من نسخة واحدة (قفل يتعافى تلقائياً بعد انهيار سابق)
    os.makedirs(appdata_dir(), exist_ok=True)
    lock = QLockFile(lock_path())
    lock.setStaleLockTime(60000)
    if not lock.tryLock(100):
        QMessageBox.warning(None, "PrintBot", "PrintBot يعمل بالفعل.")
        return 0

    config = Config()
    set_autostart(config.auto_start)

    tray = TrayApp(app, config)

    hidden = "--hidden" in sys.argv

    if not config.bot_token:
        tray.run_wizard()

    if config.bot_token:
        tray.start_bot()

    if not hidden:
        tray.show_window()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
