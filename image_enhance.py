"""
image_enhance.py
تحسين وضوح صورة مستند (JPG/PNG) بشكل شبيه بمنظفات الماسح الضوئي،
بدون كشف حواف أو تصحيح منظور تلقائي (لأن هذه الخطوة غير مضمونة النجاح دائماً).
"""

import cv2
import numpy as np
from PIL import Image, ImageEnhance


def enhance_document(image_path: str, output_path: str, mode: str = "auto") -> str:
    """
    يحسّن صورة مستند لتصبح أوضح عند الطباعة.

    mode:
      - "auto":  يزيل الظلال/الإضاءة غير المتساوية ويحسّن التباين المحلي مع الحفاظ
                 على التدرجات (لا يحوّل الصورة لأبيض/أسود حاد) - الأنسب لمعظم الحالات
      - "bw":    تحويل قوي لأبيض/أسود حاد (نصوص واضحة فقط) - مناسب لصفحات نص بحتة
      - "color": الإبقاء على الألوان مع تحسين التباين والوضوح - للمستندات الملونة

    يُرجع مسار الصورة المحسّنة (PNG).
    """
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"تعذر قراءة الصورة: {image_path}")

    if mode == "auto":
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # إزالة الظلال/الإضاءة غير المتساوية عبر تقدير الخلفية وقسمة الصورة عليها
        # (هذه هي التقنية القياسية لتصحيح إضاءة صور المستندات الملتقطة بالهاتف)
        background = cv2.GaussianBlur(gray, (0, 0), sigmaX=21, sigmaY=21)
        normalized = cv2.divide(gray, background, scale=255)
        normalized = np.clip(normalized, 0, 255).astype(np.uint8)

        # تحسين التباين المحلي بلطف (بدون تحويل حاد لأبيض/أسود)
        clahe = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8))
        enhanced = clahe.apply(normalized)

        # تنعيم خفيف لتقليل تشويش الكاميرا ثم شحذ لطيف لزيادة وضوح النص
        denoised = cv2.bilateralFilter(enhanced, d=5, sigmaColor=40, sigmaSpace=40)
        blurred = cv2.GaussianBlur(denoised, (0, 0), sigmaX=3)
        sharpened = cv2.addWeighted(denoised, 1.4, blurred, -0.4, 0)

        cv2.imwrite(output_path, sharpened)

    elif mode == "bw":
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        thresh = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=25,
            C=15,
        )
        cv2.imwrite(output_path, thresh)

    else:  # color
        pil_img = Image.open(image_path).convert("RGB")
        pil_img = ImageEnhance.Contrast(pil_img).enhance(1.3)
        pil_img = ImageEnhance.Sharpness(pil_img).enhance(1.5)
        pil_img = ImageEnhance.Brightness(pil_img).enhance(1.05)
        pil_img.save(output_path)

    return output_path


# أبعاد أحجام الورق الشائعة بالمليمتر (عرض × ارتفاع - اتجاه عمودي)
PAPER_SIZES_MM = {
    "A4": (210, 297),
    "A3": (297, 420),
    "Letter": (215.9, 279.4),
}


def image_to_pdf(image_path: str, pdf_path: str, paper: str = "A4", dpi: int = 200) -> str:
    """
    تحويل صورة إلى ملف PDF من صفحة واحدة بحجم الورق المحدد (وليس بحجم الصورة نفسها).
    يتم تكبير/تصغير الصورة لتملأ أكبر مساحة ممكنة من الصفحة مع الحفاظ على النسب
    (بدون تشويه أو قص)، وتوسيطها إذا بقيت هوامش بيضاء بسبب اختلاف النسبة.
    """
    img = Image.open(image_path).convert("RGB")

    w_mm, h_mm = PAPER_SIZES_MM.get(paper, PAPER_SIZES_MM["A4"])
    page_w = int(w_mm / 25.4 * dpi)
    page_h = int(h_mm / 25.4 * dpi)

    canvas = Image.new("RGB", (page_w, page_h), "white")

    img_w, img_h = img.size
    scale = min(page_w / img_w, page_h / img_h)
    new_w, new_h = max(1, int(img_w * scale)), max(1, int(img_h * scale))
    img_resized = img.resize((new_w, new_h), Image.LANCZOS)

    x = (page_w - new_w) // 2
    y = (page_h - new_h) // 2
    canvas.paste(img_resized, (x, y))

    canvas.save(pdf_path, "PDF", resolution=dpi)
    return pdf_path