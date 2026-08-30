"""إدارة الإعدادات: تحميل/حفظ config.json في %APPDATA%\\PrintBot\\."""
import copy
import json
import os
import sys
import uuid

APP_NAME = "PrintBot"

DEFAULT_CONFIG = {
    "bot_token": "",
    "allowed_chat_ids": [],
    "sumatra_path": "",
    "printers": [],
    "default": {"printer_key": "", "copies": 1, "paper": "A4", "color": "color"},
    "auto_start": True,
}


def appdata_dir() -> str:
    """مجلد بيانات التطبيق الخاص بالمستخدم (قابل للكتابة دون صلاحيات إدارية)."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_NAME)


def logs_dir() -> str:
    return os.path.join(appdata_dir(), "logs")


def temp_dir() -> str:
    return os.path.join(appdata_dir(), "temp")


def config_path() -> str:
    return os.path.join(appdata_dir(), "config.json")


def lock_path() -> str:
    return os.path.join(appdata_dir(), "printbot.lock")


def _bundle_dir() -> str:
    """مجلد موارد التطبيق عند التجميع، أو جذر المشروع عند التشغيل من المصدر."""
    if getattr(sys, "frozen", False):
        # في PyInstaller 6 (one-folder) توجد ملفات البيانات في sys._MEIPASS (مجلد _internal)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return meipass
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_sumatra_path() -> str:
    p = os.path.join(_bundle_dir(), "SumatraPDF.exe")
    return p if os.path.exists(p) else ""


def default_icon_path() -> str:
    p = os.path.join(_bundle_dir(), "PrintBot.ico")
    return p if os.path.exists(p) else ""


class Config:
    def __init__(self, path: str = None):
        self.path = path or config_path()
        self.data = self._load()

    def _load(self) -> dict:
        data = copy.deepcopy(DEFAULT_CONFIG)
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data.update(loaded)
            except (json.JSONDecodeError, OSError):
                data = copy.deepcopy(DEFAULT_CONFIG)

        data.setdefault("default", {}).update(DEFAULT_CONFIG["default"])

        # ترحيل الصيغة القديمة (خريطة طابعات {مفتاح: اسم}) إلى قائمة طابعات
        printers = data.get("printers")
        if isinstance(printers, dict):
            data["printers"] = [
                {"id": k, "name": v, "label": v} for k, v in printers.items()
            ]
        if not isinstance(data.get("printers"), list):
            data["printers"] = []

        # ترحيل الصيغة القديمة (allowed_chat_id واحد) إلى قائمة allowed_chat_ids
        if "allowed_chat_id" in data:
            old = data.pop("allowed_chat_id")
            ids = data.get("allowed_chat_ids", [])
            if not isinstance(ids, list):
                ids = [ids] if ids else []
            try:
                old = int(old)
            except (TypeError, ValueError):
                old = 0
            if old and old not in ids:
                ids.append(old)
            data["allowed_chat_ids"] = ids

        ids = data.get("allowed_chat_ids", [])
        if not isinstance(ids, list):
            ids = [ids] if ids else []
        seen = set()
        clean = []
        for i in ids:
            try:
                v = int(i)
            except (TypeError, ValueError):
                continue
            if v and v not in seen:
                seen.add(v)
                clean.append(v)
        data["allowed_chat_ids"] = clean

        return data

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    # ---------- التوكن والمستخدم ----------
    @property
    def bot_token(self) -> str:
        return str(self.data.get("bot_token", "")).strip()

    @bot_token.setter
    def bot_token(self, value: str) -> None:
        self.data["bot_token"] = str(value).strip()

    @property
    def allowed_chat_ids(self) -> list:
        return self.data["allowed_chat_ids"]

    def is_allowed(self, chat_id: int) -> bool:
        try:
            return int(chat_id) in self.allowed_chat_ids
        except (TypeError, ValueError):
            return False

    def add_allowed_chat_id(self, chat_id: int) -> bool:
        try:
            chat_id = int(chat_id)
        except (TypeError, ValueError):
            return False
        if chat_id <= 0 or chat_id in self.allowed_chat_ids:
            return False
        self.allowed_chat_ids.append(chat_id)
        return True

    def remove_allowed_chat_id(self, chat_id: int) -> None:
        try:
            self.allowed_chat_ids.remove(int(chat_id))
        except (TypeError, ValueError):
            pass

    def clear_allowed_chat_ids(self) -> None:
        self.data["allowed_chat_ids"] = []

    @property
    def auto_start(self) -> bool:
        return bool(self.data.get("auto_start", True))

    @auto_start.setter
    def auto_start(self, value: bool) -> None:
        self.data["auto_start"] = bool(value)

    # ---------- SumatraPDF ----------
    @property
    def sumatra_path(self) -> str:
        return self.data.get("sumatra_path") or default_sumatra_path()

    @sumatra_path.setter
    def sumatra_path(self, value: str) -> None:
        self.data["sumatra_path"] = value

    # ---------- الطابعات ----------
    @property
    def printers(self) -> list:
        return self.data["printers"]

    def add_printer(self, name: str, label: str = "") -> str:
        pid = uuid.uuid4().hex[:8]
        self.data["printers"].append(
            {"id": pid, "name": name, "label": label or name}
        )
        return pid

    def remove_printer(self, pid: str) -> None:
        self.data["printers"] = [p for p in self.data["printers"] if p["id"] != pid]
        if self.data["default"]["printer_key"] == pid:
            self.data["default"]["printer_key"] = ""

    def get_printer(self, pid: str):
        for p in self.data["printers"]:
            if p["id"] == pid:
                return p
        return None

    def printer_name(self, pid: str) -> str:
        p = self.get_printer(pid)
        return p["name"] if p else ""

    def printer_label(self, pid: str) -> str:
        p = self.get_printer(pid)
        return p["label"] if p else ""

    # ---------- الإعدادات الافتراضية ----------
    @property
    def default(self) -> dict:
        return self.data["default"]

    def set_default(self, **kwargs) -> None:
        self.data["default"].update(kwargs)
