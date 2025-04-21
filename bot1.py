import os
import logging
import uuid
import tempfile
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ChatAction
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
    ConversationHandler,
    run_async,
)
import yt_dlp

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
SELECT_LANG, SELECT_TYPE, WAIT_FOR_URL = range(3)

# Bot token (hardcoded)         
TOKEN = "7878902861:AAE_7lmD0AnRHgNPYXzwQbNsQnhoYZCfUNQ"

# Optional: set custom ffmpeg/ffprobe location via env var
FFMPEG_PATH = os.getenv('FFMPEG_PATH', 'ffmpeg')

# Localization strings
i18n = {
    'en': {
        'welcome': "👋 Welcome! Please choose your language:",
        'ask_type': "What are you downloading?",
        'selected': "You selected: {choice}.",
        'ask_url': "Send me the URL.",
        'downloading': "⏳ Downloading now, please wait...",
        'not_found': "❌ Download finished, but file not found.",
        'error_url': "❌ Could not download media. Please ensure the URL is correct.",
        'unexpected': "❌ An unexpected error occurred: {error}",
        'again': "What else would you like to download?",
        'cancelled': "Operation cancelled. Use /start to try again.",
    },
    'uz': {
        'welcome': "👋 Salom! Iltimos, tilni tanlang:",
        'ask_type': "Nima yuklamoqchisiz?",
        'selected': "Siz tanladingiz: {choice}.",
        'ask_url': "URL manzilini yuboring.",
        'downloading': "⏳ Yuklanmoqda, iltimos kuting...",
        'not_found': "❌ Yuklash yakunlandi, ammo fayl topilmadi.",
        'error_url': "❌ Media yuklab bo'lmadi. Iltimos URL tog'ri ekanligini tekshiring.",
        'unexpected': "❌ Kutilmagan xatolik yuz berdi: {error}",
        'again': "Yana nima yuklamoqchisiz?",
        'cancelled': "Amal bekor qilindi. Yana /start buyrug'i bilan boshlang.",
    }
}

@run_async
def start(update: Update, context):
    """Entry point: ask user to choose language"""
    keyboard = [
        [InlineKeyboardButton("🇺🇿 Uzbek", callback_data='lang_uz'),
         InlineKeyboardButton("🇬🇧 English", callback_data='lang_en')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(i18n['en']['welcome'], reply_markup=reply_markup)
    return SELECT_LANG

def language_handler(update: Update, context):
    """Handle language selection and ask download type"""
    query = update.callback_query
    query.answer()
    lang = query.data.split('_')[1]
    context.user_data['lang'] = lang
    texts = i18n[lang]
    keyboard = [
        [InlineKeyboardButton("📹 " + ("Download Video" if lang == 'en' else "Video yuklash"), callback_data='type_video'),
         InlineKeyboardButton("🎵 " + ("Download Audio" if lang == 'en' else "Audio yuklash"), callback_data='type_audio')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(texts['ask_type'], reply_markup=reply_markup)
    return SELECT_TYPE

def type_handler(update: Update, context):
    """Handle media type selection and ask for URL"""
    query = update.callback_query
    query.answer()
    mode = query.data.split('_')[1]
    context.user_data['mode'] = mode
    lang = context.user_data.get('lang', 'en')
    texts = i18n[lang]
    choice_text = ("Video" if mode == 'video' else "Audio")
    query.edit_message_text(texts['selected'].format(choice=choice_text))
    query.bot.send_message(chat_id=query.message.chat_id, text=texts['ask_url'])
    return WAIT_FOR_URL

@run_async
def download_media(update: Update, context):
    """Download the media from given URL and send back; then ask again"""
    url = update.message.text.strip()
    mode = context.user_data.get('mode', 'audio')
    lang = context.user_data.get('lang', 'en')
    texts = i18n[lang]
    chat_id = update.effective_chat.id

    context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    update.message.reply_text(texts['downloading'])

    temp_dir = tempfile.mkdtemp(prefix=f"yt_{chat_id}_")
    uid = uuid.uuid4().hex
    out_tmpl = os.path.join(temp_dir, f"{mode}_{uid}.%(ext)s")

    ydl_opts = {
        'format': 'bestaudio/best' if mode == 'audio' else 'bestvideo+bestaudio/best',
        'outtmpl': out_tmpl,
        'noplaylist': False,
        'merge_output_format': 'mp4' if mode == 'video' else None,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192'
        }] if mode == 'audio' else [],
        'ffmpeg_location': FFMPEG_PATH,
        'concurrent_fragment_downloads': 4,
    }

    def send_file(path):
        action = ChatAction.UPLOAD_AUDIO if mode == 'audio' else ChatAction.UPLOAD_VIDEO
        context.bot.send_chat_action(chat_id=chat_id, action=action)
        if mode == 'audio':
            with open(path, 'rb') as f:
                update.message.reply_audio(audio=f)
        else:
            with open(path, 'rb') as f:
                update.message.reply_video(video=f)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            file_path = (os.path.splitext(filename)[0] + '.mp3') if mode == 'audio' else filename
        if os.path.exists(file_path):
            send_file(file_path)
        else:
            update.message.reply_text(texts['not_found'])
    except yt_dlp.utils.DownloadError as de:
        logger.warning("Primary download failed, retrying fallback: %s", de)
        try:
            fallback_opts = {
                'format': 'bestaudio' if mode == 'audio' else 'best',
                'outtmpl': out_tmpl,
                'noplaylist': False
            }
            with yt_dlp.YoutubeDL(fallback_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                fallback_file = ydl.prepare_filename(info)
            if os.path.exists(fallback_file):
                send_file(fallback_file)
            else:
                update.message.reply_text(texts['not_found'])
        except Exception as e2:
            logger.error("Fallback failed: %s", e2)
            update.message.reply_text(texts['error_url'])
    except Exception as e:
        logger.error("Unexpected error: %s", e)
        update.message.reply_text(texts['unexpected'].format(error=e))
    finally:
        # Cleanup
        for f in os.listdir(temp_dir):
            try:
                os.remove(os.path.join(temp_dir, f))
            except Exception as e:
                logger.warning(f"Failed to remove file: {e}")
        try:
            os.rmdir(temp_dir)
        except Exception as e:
            logger.warning(f"Failed to remove directory: {e}")

    # Ask again
    keyboard = [
        [InlineKeyboardButton("📹 " + ("Video" if lang == 'en' else "Video yuklash"), callback_data='type_video'),
         InlineKeyboardButton("🎵 " + ("Audio" if lang == 'en' else "Audio yuklash"), callback_data='type_audio')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    context.bot.send_message(chat_id=chat_id, text=texts['again'], reply_markup=reply_markup)
    return SELECT_TYPE

@run_async
def cancel(update: Update, context):
    lang = context.user_data.get('lang', 'en')
    texts = i18n[lang]
    update.message.reply_text(texts['cancelled'])
    return ConversationHandler.END

if __name__ == '__main__':
    updater = Updater(token=TOKEN, use_context=True)
    dp = updater.dispatcher
    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            SELECT_LANG: [CallbackQueryHandler(language_handler, pattern='^lang_')],
            SELECT_TYPE: [CallbackQueryHandler(type_handler, pattern='^type_')],
            WAIT_FOR_URL: [MessageHandler(Filters.text & ~Filters.command, download_media)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    dp.add_handler(conv)
    updater.start_polling()
    logger.info("Bot polling started.")
    updater.idle()
