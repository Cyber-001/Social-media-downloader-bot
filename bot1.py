import os
import logging
import uuid
import tempfile
from threading import Thread
from flask import Flask
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

# Flask app for health check
app = Flask(__name__)
@app.route('/')
def home():
    return '🤖 Bot is alive!'

# Conversation states
SELECT_LANG, SELECT_TYPE, WAIT_FOR_URL = range(3)

# Bot token: env var fallback to hardcoded
TOKEN = os.getenv("TOKEN") or "7878902861:AAE_7lmD0AnRHgNPYXzwQbNsQnhoYZCfUNQ"
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
    """Show bilingual language selection menu"""
    keyboard = [[
        InlineKeyboardButton("🇺🇿 Uzbek", callback_data='lang_uz'),
        InlineKeyboardButton("🇬🇧 English", callback_data='lang_en')
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    prompt = "👋 Please choose your language / Iltimos, tilni tanlang:"
    update.message.reply_text(prompt, reply_markup=reply_markup)
    return SELECT_LANG


def language_handler(update: Update, context):
    query = update.callback_query
    query.answer()
    lang = query.data.split('_')[1]
    context.user_data['lang'] = lang
    texts = i18n[lang]
    keyboard = [[
        InlineKeyboardButton("📹 " + ("Download Video" if lang=='en' else "Video yuklash"), callback_data='type_video'),
        InlineKeyboardButton("🎵 " + ("Download Audio" if lang=='en' else "Audio yuklash"), callback_data='type_audio')
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(texts['ask_type'], reply_markup=reply_markup)
    return SELECT_TYPE


def type_handler(update: Update, context):
    query = update.callback_query
    query.answer()
    mode = query.data.split('_')[1]
    context.user_data['mode'] = mode
    lang = context.user_data.get('lang', 'en')
    texts = i18n[lang]
    choice_text = "Video" if mode=='video' else "Audio"
    query.edit_message_text(texts['selected'].format(choice=choice_text))
    context.bot.send_message(chat_id=query.message.chat_id, text=texts['ask_url'])
    return WAIT_FOR_URL

@run_async
def download_media(update: Update, context):
    url = update.message.text.strip()
    mode = context.user_data.get('mode', 'audio')
    lang = context.user_data.get('lang', 'en')
    texts = i18n[lang]
    chat_id = update.effective_chat.id

    update.message.reply_text(texts['downloading'])
    context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_AUDIO if mode=='audio' else ChatAction.UPLOAD_VIDEO)

    temp_dir = tempfile.mkdtemp(prefix=f"dl_{chat_id}_")
    uid = uuid.uuid4().hex
    out_tmpl = os.path.join(temp_dir, f"{mode}_{uid}.%(ext)s")

    ydl_opts = {
        'format': 'bestaudio/best' if mode=='audio' else 'best',
        'outtmpl': out_tmpl,
        'noplaylist': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192'
        }] if mode=='audio' else [],
        'ffmpeg_location': FFMPEG_PATH,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = ydl.prepare_filename(info)
            if mode=='audio':
                filepath = os.path.splitext(filepath)[0] + '.mp3'
        if os.path.exists(filepath):
            if mode=='audio':
                update.message.reply_audio(audio=open(filepath, 'rb'))
            else:
                update.message.reply_video(video=open(filepath, 'rb'))
        else:
            update.message.reply_text(texts['not_found'])
    except Exception as e:
        logger.error(f"Download error: {e}")
        update.message.reply_text(texts['error_url'])
    finally:
        for f in os.listdir(temp_dir):
            try:
                os.remove(os.path.join(temp_dir, f))
            except:
                pass
        try:
            os.rmdir(temp_dir)
        except:
            pass

    # Ask again
    keyboard = [[
        InlineKeyboardButton("📹 " + ("Video" if lang=='en' else "Video yuklash"), callback_data='type_video'),
        InlineKeyboardButton("🎵 " + ("Audio" if lang=='en' else "Audio yuklash"), callback_data='type_audio')
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    context.bot.send_message(chat_id=chat_id, text=texts['again'], reply_markup=reply_markup)
    return SELECT_TYPE

@run_async
def cancel(update: Update, context):
    lang = context.user_data.get('lang', 'en')
    update.message.reply_text(i18n[lang]['cancelled'])
    return ConversationHandler.END


def start_bot():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            SELECT_LANG: [CallbackQueryHandler(language_handler, pattern='^lang_')],
            SELECT_TYPE: [CallbackQueryHandler(type_handler, pattern='^type_')],
            WAIT_FOR_URL: [MessageHandler(Filters.text & ~Filters.command, download_media)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    dp.add_handler(conv)
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    Thread(target=start_bot).start()
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
