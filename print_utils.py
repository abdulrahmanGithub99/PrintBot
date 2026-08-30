"""إرسال ملفات PDF للطباعة الصامتة (بدون فتح أي نافذة) عبر SumatraPDF."""
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw


def print_pdf(pdf_path, printer_name, sumatra_path,
              copies=1, paper="A4", color="color") -> None:
    """يطبع ملف PDF مباشرة دون فتح أي نافذة.

    printer_name : اسم الطابعة بالضبط كما يظهر في ويندوز.
    color        : "color" أو "monochrome".
    """
    if not sumatra_path or not os.path.exists(sumatra_path):
        raise FileNotFoundError(
            "SumatraPDF غير موجود في المسار المحدد: " + str(sumatra_path)
        )
    if not printer_name:
        raise ValueError("لم يتم اختيار طابعة.")

    settings = f"paper={paper},copies={copies},fit,{color}"

    cmd = [
        sumatra_path,
        "-print-to", printer_name,
        "-print-settings", settings,
        "-silent",
        pdf_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(
            f"فشلت عملية الطباعة (كود {result.returncode}): "
            f"{result.stderr or result.stdout or 'سبب غير معروف'}"
        )


def print_test_page(printer_name, sumatra_path) -> None:
    """ينشئ صفحة اختبار بسيطة ويرسلها للطابعة للتحقق من صحة الاسم."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        pdf_path = f.name

    try:
        img = Image.new("RGB", (1654, 2339), "white")  # A4 بمقاس 200 نقطة/بوصة
        d = ImageDraw.Draw(img)
        d.rectangle([100, 100, 1554, 2239], outline="black", width=4)
        d.line([150, 1100, 1504, 1100], fill="black", width=2)
        d.text((760, 1120), "PrintBot Test Page", fill="black")
        d.text((700, 1200), "صفحة اختبار الطابعة", fill="black")
        img.save(pdf_path, "PDF", resolution=200)

        print_pdf(pdf_path, printer_name, sumatra_path, copies=1, paper="A4", color="color")
    finally:
        try:
            os.remove(pdf_path)
        except OSError:
            pass
