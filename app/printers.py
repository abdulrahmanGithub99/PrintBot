"""اكتشاف الطابعات المثبّتة على الويندوز عبر win32print."""
import win32print


def list_printers() -> list:
    """يعيد قائمة بأسماء الطابعات المتاحة (المحلية والمتصلة بالشبكة)."""
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    names = []
    seen = set()
    try:
        info = win32print.EnumPrinters(flags, None, 2)
    except Exception:
        info = []

    for entry in info:
        name = entry.get("pPrinterName", "") if isinstance(entry, dict) else ""
        if name and name not in seen:
            seen.add(name)
            names.append(name)

    names.sort()
    return names
