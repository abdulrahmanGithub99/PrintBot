"""تشغيل بوت تيليجرام في خيط منفصل مع إدارة يدوية لدورة الأحداث (asyncio)."""
import asyncio
import logging
import os
import threading
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Conflict
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from image_enhance import enhance_document, image_to_pdf
import print_utils
from app import strings as S
from app.config import temp_dir

COPIES_OPTIONS = [1, 2, 3, 5]
PAPER_OPTIONS = ["A4", "A3", "Letter"]
COLOR_OPTIONS = [("color", "🎨 ملون"), ("monochrome", "⚫ أبيض/أسود")]

IMG_EXTS = (".png", ".jpg", ".jpeg")


def _ensure_temp() -> str:
    d = temp_dir()
    os.makedirs(d, exist_ok=True)
    return d


class BotHandlers:
    """منطق استقبال الملفات والطباعة، معزول عن إدارة الخيط."""

    def __init__(self, config, callbacks):
        self.config = config
        self.cb = callbacks

    # ---------- أدوات مساعدة ----------
    def _is_allowed(self, chat_id: int) -> bool:
        return self.config.is_allowed(chat_id)

    def _notify_chat(self, update: Update) -> None:
        user = update.effective_user
        name = user.full_name if user else ""
        self.cb.chat.emit(update.effective_chat.id, name)

    def _add_temp(self, context, path: str) -> None:
        if not path:
            return
        files = context.user_data.setdefault("temp_files", [])
        files.append(path)

    def _finalize(self, context) -> None:
        for p in context.user_data.get("temp_files", []):
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
        context.user_data.clear()

    def _log(self, file, printer_label, copies, paper, result, message=""):
        self.cb.log.emit({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "file": file,
            "printer": printer_label,
            "copies": copies,
            "paper": paper,
            "result": result,
            "message": message,
        })

    def prepare_pdf_for_paper(self, context, paper: str) -> str:
        source_type = context.user_data.get("source_type")
        source_path = context.user_data.get("source_path")

        if not source_path or not os.path.exists(source_path):
            raise FileNotFoundError("لم يعد الملف متاحاً، أرسله من جديد.")

        if source_type == "image":
            ts = datetime.now().strftime("%Y%m%d_%H%M%S%f")
            pdf_path = os.path.join(_ensure_temp(), f"doc_{ts}.pdf")
            image_to_pdf(source_path, pdf_path, paper=paper)
            self._add_temp(context, pdf_path)
            return pdf_path

        return source_path

    # ---------- أوامر عامة ----------
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        if self._is_allowed(chat_id):
            await update.message.reply_text("أهلاً! أرسل ملف PDF أو صورة (PNG/JPG).")
        else:
            self._notify_chat(update)
            await update.message.reply_text(
                f"🚫 غير مصرح لك باستخدام هذا البوت.\nChat ID الخاص بك: {chat_id}"
            )

    async def whoami(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self._notify_chat(update)
        await update.message.reply_text(f"Chat ID: {update.effective_chat.id}")

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        if self._is_allowed(chat_id):
            await update.message.reply_text(S.MSG_BOT_READY)
        else:
            self._notify_chat(update)
            await update.message.reply_text(
                f"🚫 غير مصرح لك باستخدام هذا البوت.\nChat ID الخاص بك: {chat_id}"
            )

    async def on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        err = context.error
        self._log("", "", 0, "", "error", str(err))

    # ---------- استقبال الملفات ----------
    async def handle_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            self._notify_chat(update)
            await update.message.reply_text("🚫 غير مصرح لك باستخدام هذا البوت.")
            return

        msg = update.message
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if msg.document:
            file_obj = await msg.document.get_file()
            file_name = os.path.basename(msg.document.file_name or f"file_{timestamp}")
        elif msg.photo:
            file_obj = await msg.photo[-1].get_file()
            file_name = f"photo_{timestamp}.jpg"
        else:
            await msg.reply_text("الرجاء إرسال ملف PDF أو صورة PNG/JPG فقط.")
            return

        context.user_data["display_name"] = file_name

        local_path = os.path.join(_ensure_temp(), file_name)
        await file_obj.download_to_drive(local_path)
        self._add_temp(context, local_path)

        ext = os.path.splitext(file_name)[1].lower()

        try:
            if ext in IMG_EXTS:
                context.user_data["source_type"] = "image"
                context.user_data["source_path"] = local_path

                keyboard = [
                    [InlineKeyboardButton("✨ تحسين الوضوح", callback_data="enhance:yes")],
                    [InlineKeyboardButton("🖼 بدون تحسين", callback_data="enhance:no")],
                ]
                await msg.reply_text(
                    "هل تريد تحسين وضوح الصورة قبل الطباعة؟",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
                return

            elif ext == ".pdf":
                context.user_data["source_type"] = "pdf"
                context.user_data["source_path"] = local_path
            else:
                await msg.reply_text("صيغة غير مدعومة. أرسل PDF أو PNG أو JPG فقط.")
                self._finalize(context)
                return

        except Exception as e:
            self._log(file_name, "", 0, "", "error", str(e))
            await msg.reply_text(f"⚠️ حدث خطأ أثناء تجهيز الملف: {e}")
            self._finalize(context)
            return

        keyboard = [
            [InlineKeyboardButton("🖨 طباعة سريعة (الإعدادات الافتراضية)", callback_data="quick_print")],
            [InlineKeyboardButton("⚙️ تخصيص إعدادات الطباعة", callback_data="customize_start")],
        ]
        await msg.reply_text("الملف جاهز، كيف تريد الطباعة؟", reply_markup=InlineKeyboardMarkup(keyboard))

    # ---------- اختيار التحسين للصور ----------
    async def set_enhance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        choice = query.data.split(":", 1)[1]

        source_path = context.user_data.get("source_path")

        if choice == "yes":
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                enhanced_path = os.path.join(_ensure_temp(), f"enhanced_{timestamp}.png")
                enhance_document(source_path, enhanced_path, mode="auto")
                self._add_temp(context, enhanced_path)

                with open(enhanced_path, "rb") as f:
                    await query.message.reply_photo(photo=f, caption="✅ هذا شكل الصورة بعد التحسين")

                context.user_data["source_path"] = enhanced_path
            except Exception as e:
                self._log(context.user_data.get("display_name", ""), "", 0, "", "error", str(e))
                await query.edit_message_text(f"⚠️ فشل تحسين الصورة: {e}")
                self._finalize(context)
                return

        keyboard = [
            [InlineKeyboardButton("🖨 طباعة سريعة (الإعدادات الافتراضية)", callback_data="quick_print")],
            [InlineKeyboardButton("⚙️ تخصيص إعدادات الطباعة", callback_data="customize_start")],
        ]
        await query.edit_message_text("الملف جاهز، كيف تريد الطباعة؟", reply_markup=InlineKeyboardMarkup(keyboard))

    # ---------- الطباعة السريعة ----------
    async def quick_print(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        d = self.config.default
        printer = self.config.get_printer(d.get("printer_key"))
        if not printer:
            await query.edit_message_text("لم يتم تحديد طابعة افتراضية. أضفها من إعدادات التطبيق أولاً.")
            return

        paper = d.get("paper", "A4")
        copies = int(d.get("copies", 1))
        color = d.get("color", "color")
        label = printer["label"]

        try:
            pdf_path = self.prepare_pdf_for_paper(context, paper)
            print_utils.print_pdf(
                pdf_path, printer["name"], self.config.sumatra_path,
                copies=copies, paper=paper, color=color,
            )
            self._log(context.user_data.get("display_name", ""), label, copies, paper, "ok")
            await query.edit_message_text(
                f"✅ تم إرسال الملف للطباعة\nالطابعة: {label} | نسخ: {copies} | ورق: {paper}"
            )
        except Exception as e:
            self._log(context.user_data.get("display_name", ""), label, copies, paper, "fail", str(e))
            await query.edit_message_text(f"❌ فشلت الطباعة: {e}")
        finally:
            self._finalize(context)

    # ---------- تخصيص الطباعة ----------
    async def customize_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        printers = self.config.printers
        if not printers:
            await query.edit_message_text("لا توجد طابعات محفوظة. أضفها من إعدادات التطبيق أولاً.")
            return

        keyboard = [
            [InlineKeyboardButton(p["label"], callback_data=f"set_printer:{p['id']}")]
            for p in printers
        ]
        await query.edit_message_text("١) اختر الطابعة:", reply_markup=InlineKeyboardMarkup(keyboard))

    async def set_printer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        printer_key = query.data.split(":", 1)[1]
        context.user_data["printer_key"] = printer_key

        keyboard = [[InlineKeyboardButton(str(c), callback_data=f"set_copies:{c}") for c in COPIES_OPTIONS]]
        await query.edit_message_text("٢) عدد النسخ:", reply_markup=InlineKeyboardMarkup(keyboard))

    async def set_copies(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        copies = int(query.data.split(":", 1)[1])
        context.user_data["copies"] = copies

        keyboard = [[InlineKeyboardButton(p, callback_data=f"set_paper:{p}") for p in PAPER_OPTIONS]]
        await query.edit_message_text("٣) حجم الورق:", reply_markup=InlineKeyboardMarkup(keyboard))

    async def set_paper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        paper = query.data.split(":", 1)[1]
        context.user_data["paper"] = paper

        keyboard = [[InlineKeyboardButton(label, callback_data=f"set_color:{value}")] for value, label in COLOR_OPTIONS]
        await query.edit_message_text("٤) نوع الطباعة:", reply_markup=InlineKeyboardMarkup(keyboard))

    async def set_color(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        color = query.data.split(":", 1)[1]
        context.user_data["color"] = color

        d = context.user_data
        label = self.config.printer_label(d.get("printer_key"))
        summary = (
            f"الطابعة: {label}\n"
            f"النسخ: {d['copies']}\n"
            f"الورق: {d['paper']}\n"
            f"اللون: {'ملون' if color == 'color' else 'أبيض/أسود'}"
        )
        keyboard = [
            [InlineKeyboardButton("✅ تأكيد الطباعة", callback_data="confirm_print")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="cancel_print")],
        ]
        await query.edit_message_text(f"مراجعة الإعدادات:\n\n{summary}", reply_markup=InlineKeyboardMarkup(keyboard))

    async def confirm_print(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        d = context.user_data
        printer = self.config.get_printer(d.get("printer_key"))
        if not printer:
            await query.edit_message_text("الطابعة المختارة لم تعد موجودة.")
            self._finalize(context)
            return

        paper = d.get("paper", "A4")
        copies = int(d.get("copies", 1))
        color = d.get("color", "color")
        label = printer["label"]

        try:
            pdf_path = self.prepare_pdf_for_paper(context, paper)
            print_utils.print_pdf(
                pdf_path, printer["name"], self.config.sumatra_path,
                copies=copies, paper=paper, color=color,
            )
            self._log(context.user_data.get("display_name", ""), label, copies, paper, "ok")
            await query.edit_message_text("✅ تم إرسال الملف للطباعة بالإعدادات المخصصة.")
        except Exception as e:
            self._log(context.user_data.get("display_name", ""), label, copies, paper, "fail", str(e))
            await query.edit_message_text(f"❌ فشلت الطباعة: {e}")
        finally:
            self._finalize(context)

    async def cancel_print(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        self._finalize(context)
        await query.edit_message_text("تم الإلغاء.")


class BotRunner:
    """يدير تشغيل/إيقاف البوت في خيط خلفي بمعزل عن واجهة Qt."""

    def __init__(self, config, callbacks):
        self.config = config
        self.cb = callbacks
        self.handlers = BotHandlers(config, callbacks)
        self._thread = None
        self._loop = None
        self._stop_event = None
        self._app = None
        self._running = threading.Event()
        self._conflict = False
        self._conflict_detail = ""

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    def start(self) -> None:
        if self.is_running or (self._thread and self._thread.is_alive()):
            return
        self._thread = threading.Thread(target=self._run, name="PrintBotBot", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._thread:
            return
        if self._loop and self._stop_event:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        self._thread.join(timeout=15)
        self._thread = None

    # ---------- التنفيذ داخل الخيط ----------
    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_main())
        except Exception as e:
            self.cb.status.emit("error", str(e))
        finally:
            self._running.clear()
            self._loop.close()
            self._loop = None
            self._stop_event = None
            self._app = None

    async def _async_main(self) -> None:
        self._app = Application.builder().token(self.config.bot_token).build()
        self._register_handlers()
        self._stop_event = asyncio.Event()
        self._conflict = False
        self._conflict_detail = ""

        await self._app.initialize()
        await self._app.updater.start_polling(
            drop_pending_updates=True,
            error_callback=self._polling_error_callback,
        )
        await self._app.start()

        self._running.set()
        self.cb.status.emit("running", "")
        await self._notify_ready()

        await self._stop_event.wait()

        await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()
        if not self._conflict:
            self.cb.status.emit("stopped", "")

    async def _notify_ready(self) -> None:
        for cid in self.config.allowed_chat_ids:
            try:
                await self._app.bot.send_message(chat_id=cid, text=S.MSG_BOT_STARTED)
            except Exception:
                pass

    def _polling_error_callback(self, exc) -> None:
        """يُستدعى من حلقة الاستطلاع عند حدوث TelegramError (مثل تعارض 409)."""
        if isinstance(exc, Conflict):
            self._conflict = True
            self._conflict_detail = S.STATUS_CONFLICT
            self.cb.status.emit("conflict", S.STATUS_CONFLICT)
            if self._stop_event:
                self._stop_event.set()
        else:
            logging.getLogger("telegram.ext").exception(
                "Exception happened while polling for updates.", exc_info=exc
            )

    def _register_handlers(self) -> None:
        h = self.handlers
        self._app.add_handler(CommandHandler("start", h.start))
        self._app.add_handler(CommandHandler("whoami", h.whoami))
        self._app.add_handler(CommandHandler("status", h.status))
        self._app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, h.handle_file))

        self._app.add_handler(CallbackQueryHandler(h.quick_print, pattern="^quick_print$"))
        self._app.add_handler(CallbackQueryHandler(h.customize_start, pattern="^customize_start$"))
        self._app.add_handler(CallbackQueryHandler(h.set_enhance, pattern="^enhance:"))
        self._app.add_handler(CallbackQueryHandler(h.set_printer, pattern="^set_printer:"))
        self._app.add_handler(CallbackQueryHandler(h.set_copies, pattern="^set_copies:"))
        self._app.add_handler(CallbackQueryHandler(h.set_paper, pattern="^set_paper:"))
        self._app.add_handler(CallbackQueryHandler(h.set_color, pattern="^set_color:"))
        self._app.add_handler(CallbackQueryHandler(h.confirm_print, pattern="^confirm_print$"))
        self._app.add_handler(CallbackQueryHandler(h.cancel_print, pattern="^cancel_print$"))

        self._app.add_error_handler(h.on_error)
