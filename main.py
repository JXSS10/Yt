import os
import re
import yt_dlp
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import MessageNotModified
from plugins.config import Config
# --- بيانات البوت (تم استيرادها من config.py) ---
# API_ID = ваш_api_id  # استبدل بـ API ID الخاص بك -  **الآن مستورد من config.py**
# API_HASH = "ваш_api_hash"  # استبدل بـ API Hash الخاص بك - **الآن مستورد من config.py**
# BOT_TOKEN = "ваш_bot_token"  # استبدل بـ Bot Token الخاص بك - **الآن مستورد من config.py**

# --- تهيئة البوت ---
bot = Client(
    "URL UPLOADER BOT", # استخدام SESSION_NAME من config.py
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# --- مجلد التحميل (تم استيراده من config.py) ---
DOWNLOAD_FOLDER = DOWNLOAD_LOCATION # استخدام DOWNLOAD_LOCATION من config.py
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# --- قاموس لتخزين بيانات التنزيل المؤقتة لكل مستخدم ---
download_sessions = {}

# --- دالة لتنزيل الفيديو/قائمة التشغيل ---
def download_youtube_content(url, message, format_id, user_id):
    ydl_opts = {
        'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
        'progress_hooks': [lambda d: progress_hook(d, message, user_id, "download")],
        'format': format_id, # استخدام معرف الصيغة المحدد
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            if 'entries' in info_dict: # قائمة تشغيل
                video_files = [os.path.join(DOWNLOAD_FOLDER, ydl.prepare_filename(entry)) for entry in info_dict['entries']]
            else: # فيديو واحد
                video_files = [os.path.join(DOWNLOAD_FOLDER, ydl.prepare_filename(info_dict))]
            return video_files, info_dict.get('title', 'فيديو')
    except Exception as e:
        return None, str(e)

# --- دالة عرض التقدم ---
async def progress_hook(d, message, user_id, process_type):
    if d['status'] == 'downloading' or d['status'] == 'uploading':
        percentage = float(d['_percent_str'].strip('%')) / 100 if '_percent_str' in d else 0.0
        speed = d['_speed_str'] if '_speed_str' in d else "N/A"
        eta = d['_eta_str'] if '_eta_str' in d else "N/A"
        total_size = d['_total_bytes_str'] if '_total_bytes_str' in d else "N/A"
        current_size = d['_downloaded_bytes_str'] if '_downloaded_bytes_str' in d else "N/A"

        progress_bar = progress_bar_generator(percentage)

        if process_type == "download":
            process_text = "جاري التحميل من يوتيوب"
        elif process_type == "upload":
            process_text = "جاري الرفع إلى تيليجرام"
        else:
            process_text = "جاري المعالجة"

        progress_text = (
            f"**{process_text}:**\n"
            f"📦 {progress_bar} ({percentage*100:.1f}%)\n"
            f"⬇️ السرعة: {speed} | ⏳ المتبقي: {eta}\n"
            f"حجم الملف: {current_size} / {total_size}"
        )

        session_data = download_sessions.get(user_id)
        if session_data and session_data['status_message_id'] == message.id:
            try:
                await message.edit_text(f"{session_data['initial_text']}\n\n{progress_text}", reply_markup=session_data['reply_markup'])
            except MessageNotModified:
                pass
            except Exception as e:
                print(f"خطأ في تحديث رسالة التقدم: {e}")

# --- دالة إنشاء شريط التقدم المرئي ---
def progress_bar_generator(percentage, bar_length=20):
    completed_blocks = int(round(bar_length * percentage))
    remaining_blocks = bar_length - completed_blocks
    progress_bar = '█' * completed_blocks + '░' * remaining_blocks
    return progress_bar


# --- معالج أوامر البدء ---
@bot.on_message(filters.command(["start", "help"]))
async def start_command(client, message):
    await message.reply_text(
        "أهلاً بك! أنا بوت تحميل فيديوهات يوتيوب.\n"
        "أرسل لي رابط فيديو يوتيوب أو قائمة تشغيل وسأقوم بتحميلها وإرسالها لك.\n\n"
        "**طريقة الاستخدام:**\n"
        "أرسل رابط يوتيوب (فيديو أو قائمة تشغيل) في هذه الدردشة.\n\n"
        "**الصيغ المدعومة:**\n"
        "يدعم البوت جميع صيغ روابط يوتيوب التالية:\n"
        "- `https://www.youtube.com/watch?v=VIDEO_ID`\n"
        "- `https://youtu.be/VIDEO_ID`\n"
        "- `https://www.youtube.com/playlist?list=PLAYLIST_ID`\n"
        "- ... وغيرها (انظر المثال في السؤال الأصلي)\n\n"
        "**خيارات التحميل:**\n"
        "بعد إرسال الرابط، سيتم عرض قائمة بجميع الجودات المتاحة لتختار من بينها.\n\n"
        "**ملاحظات:**\n"
        "- قد يستغرق التحميل بعض الوقت حسب حجم الفيديو وسرعة الإنترنت.\n"
        "- إذا كان الفيديو كبيرًا جدًا، قد لا يتمكن تيليجرام من إرساله مباشرة.\n"
        "- إذا واجهت أي مشاكل، يمكنك التواصل مع مطور البوت."
    )

# --- دالة لجلب صيغ الفيديو المتاحة ---
def get_video_formats(url):
    ydl_opts = {
        'format': 'best', # نحتاج فقط إلى معلومات الصيغ، ليس التنزيل الفعلي
        'listformats': True,
        'quiet': True, # منع طباعة معلومات غير ضرورية
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        formats = ydl.extract_formats(url)
        return formats

# --- معالج الرسائل النصية (روابط يوتيوب) ---
@bot.on_message(filters.text)
async def handle_youtube_url(client, message):
    url = message.text.strip()
    youtube_regex = re.compile(
        r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/(watch\?v=|embed/|v/|shorts/|playlist\?list=)?([\w-]{11,})([&|\?].*)?'
    )

    if youtube_regex.match(url):
        try:
            formats = get_video_formats(url)
            if not formats or not isinstance(formats, list):
                raise ValueError("لم يتم العثور على صيغ متاحة.")

            buttons = []
            unique_formats = {} # قاموس لتجميع الصيغ المتشابهة

            for f in formats:
                format_str = f"{f.get('format_note', 'صيغة غير محددة')} - {f.get('acodec', 'بدون صوت')}/{f.get('vcodec', 'بدون فيديو')}"
                format_id = f['format_id']

                if format_str not in unique_formats: # منع تكرار الصيغ المتشابهة
                    unique_formats[format_str] = format_id
                    buttons.append([InlineKeyboardButton(format_str, callback_data=f"format_{format_id}")])

            buttons.append([InlineKeyboardButton("إلغاء", callback_data="format_cancel")]) # زر الإلغاء دائماً موجود

            if not buttons:
                raise ValueError("لا توجد صيغ متاحة للعرض.")

            reply_markup = InlineKeyboardMarkup(buttons)
            initial_text = "اختر الجودة المطلوبة:"
            status_message = await message.reply_text(initial_text, reply_markup=reply_markup)

            # حفظ معلومات الجلسة
            download_sessions[message.from_user.id] = {
                'status_message_id': status_message.id,
                'initial_text': initial_text,
                'reply_markup': reply_markup,
                'url': url
            }

        except Exception as e:
            await message.reply_text(f"حدث خطأ أثناء جلب الجودات المتاحة:\n\n`{e}`")
    else:
        await message.reply_text("هذا ليس رابط يوتيوب صالحًا. يرجى إرسال رابط يوتيوب صحيح.")


# --- معالج استعلامات ردود الفعل ---
@bot.on_callback_query()
async def format_callback(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    session_data = download_sessions.get(user_id)
    if not session_data or callback_query.message.id != session_data['status_message_id']:
        return await callback_query.answer("انتهت صلاحية هذه الخيارات، يرجى إرسال الرابط مرة أخرى.")

    format_option = callback_query.data.replace("format_", "")

    if format_option == "cancel":
        await callback_query.message.edit_text("تم إلغاء التحميل.")
        download_sessions.pop(user_id, None)
        return await callback_query.answer()

    await callback_query.message.edit_text(f"جاري التحضير للتحميل بالصيغة المختارة...\n\n{session_data['initial_text']}", reply_markup=None)
    await callback_query.answer("بدء التحميل...")

    url = session_data['url']
    status_message = callback_query.message
    video_files, error_message = download_youtube_content(url, status_message, format_option, user_id)
    download_sessions[user_id]['video_files'] = video_files

    if video_files:
        await status_message.edit_text(f"تم التحميل بنجاح! جاري إرسال الفيديو/الفيديوهات...\n\n{session_data['initial_text']}")
        for video_file in video_files:
            if os.path.exists(video_file):
                try:
                    await bot.send_video(
                        chat_id=callback_query.message.chat.id,
                        video=video_file,
                        caption=f"تم التحميل بواسطة @{bot.me.username}",
                        progress=upload_progress_callback,
                        progress_args=(status_message, user_id, video_file, len(video_files))
                    )
                except:
                    await bot.send_document(
                        chat_id=callback_query.message.chat.id,
                        document=video_file,
                        caption=f"تم التحميل بواسطة @{bot.me.username}",
                        progress=upload_progress_callback,
                        progress_args=(status_message, user_id, video_file, len(video_files))
                    )
                os.remove(video_file)
            else:
                await status_message.reply_text(f"خطأ: الملف `{video_file}` غير موجود بعد التنزيل.")
        await status_message.delete()
        download_sessions.pop(user_id, None)
    else:
        await status_message.edit_text(f"حدث خطأ أثناء التنزيل:\n\n`{error_message}`")

# --- دالة عرض تقدم الرفع ---
async def upload_progress_callback(current, total, status_message, user_id, video_file, total_files):
    percentage = current / total
    session_data = download_sessions.get(user_id)
    if session_data and session_data['status_message_id'] == status_message.id:
        file_name = os.path.basename(video_file)
        file_index = session_data['video_files'].index(video_file) + 1 if 'video_files' in session_data and video_file in session_data['video_files'] else '?'
        progress_text = (
            f"**جاري الرفع إلى تيليجرام (الفيديو {file_index} من {total_files}):**\n"
            f"📦 {progress_bar_generator(percentage)} ({percentage*100:.1f}%)\n"
            f"اسم الملف: `{file_name}`"
        )
        try:
            await status_message.edit_text(f"{session_data['initial_text']}\n\n{progress_text}", reply_markup=session_data['reply_markup'])
        except MessageNotModified:
            pass
        except Exception as e:
            print(f"خطأ في تحديث رسالة رفع التقدم: {e}")


# --- تشغيل البوت ---
if __name__ == "__main__":
    logger.info("Bot starting...")
    try:
        bot.run()
    except Exception as e:
        logger.error(f"Bot encountered a critical error: {e}", exc_info=True)
    finally:
        logger.info("Bot stopped.")
