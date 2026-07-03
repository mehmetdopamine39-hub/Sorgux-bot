# bot.py - Webhook ile Render Uyumlu, Cloudflare Bypass
import os
import re
import sys
import time
import json
import sqlite3
import logging
import subprocess
from datetime import datetime
from typing import Dict, List, Tuple
from fake_useragent import UserAgent

# Cloudflare bypass
try:
    import cloudscraper
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "cloudscraper"])
    import cloudscraper

# Telegram
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-telegram-bot==20.7"])
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Konfigürasyon
BOT_TOKEN = "8853911485:AAEtjm2Y7640cMVlAIuYfM63JyKuyr4Lqck"
OWNER_ID = 8610336203
DB_PATH = "bot_data.db"
REQUIRED_CHANNELS = ["@iosstarturkiyee", "@rinexsorgux", "@izinsizleriz"]
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL", f"https://sorgu-botu.onrender.com")

# API'ler
APIS = {
    "tc": "https://arastir.vip/api/tc.php?tc={}",
    "adsoyad": "https://arastir.vip/api/adsoyad.php?adi={}&soyadi={}&il={}&ilce={}",
    "adres": "https://arastir.vip/api/adres.php?tc={}",
    "gsmtc": "https://arastir.vip/api/gsmtc.php?gsm={}",
    "tcgsm": "https://arastir.vip/api/tcgsm.php?tc={}",
    "isyeri": "https://arastir.vip/api/isyeri.php?tc={}",
    "sulale": "https://arastir.vip/api/sulale.php?tc={}"
}

BANNED_WORDS = ["#404", "#banned", "#kurucu", "#team", "#telegram"]

# Cloudflare scraper
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'mobile': False
    }
)

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============ VERİTABANI ============
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        join_date TEXT,
        last_active TEXT,
        is_banned INTEGER DEFAULT 0,
        query_count INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS bans (
        user_id INTEGER PRIMARY KEY,
        reason TEXT,
        ban_date TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS queries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        query_type TEXT,
        query_param TEXT,
        query_time TEXT
    )''')
    c.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (OWNER_ID,))
    conn.commit()
    conn.close()
    logger.info("✅ Veritabanı hazır")

init_db()

# ============ BOT SINIFI ============
class BotSystem:
    def __init__(self):
        self.application = None
        self.running = False
        self.start_time = datetime.now()
        self.rate_limits = {}
        self.user_states = {}

    def start(self):
        try:
            logger.info("🚀 Bot başlatılıyor...")
            self.application = Application.builder().token(BOT_TOKEN).build()
            
            # Komutlar
            self.application.add_handler(CommandHandler("start", self.start_command))
            self.application.add_handler(CommandHandler("admin", self.admin_command))
            self.application.add_handler(CommandHandler("stats", self.stats_command))
            self.application.add_handler(CommandHandler("ban", self.ban_command))
            self.application.add_handler(CommandHandler("unban", self.unban_command))
            self.application.add_handler(CommandHandler("duyuru", self.announce_command))
            self.application.add_handler(CommandHandler("clone", self.clone_command))
            self.application.add_handler(CommandHandler("restart", self.restart_command))
            self.application.add_handler(CommandHandler("stop", self.stop_command))
            
            # Callback ve mesaj
            self.application.add_handler(CallbackQueryHandler(self.callback_handler))
            self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.message_handler))
            
            self.running = True
            
            # Webhook kullan - Conflict hatasını çözer
            logger.info(f"🌐 Webhook kuruluyor: {WEBHOOK_URL}/webhook")
            self.application.run_webhook(
                listen="0.0.0.0",
                port=PORT,
                url_path="webhook",
                webhook_url=f"{WEBHOOK_URL}/webhook"
            )
            
        except Exception as e:
            logger.error(f"❌ Bot hatası: {e}")
            self.running = False
            raise

    def stop(self):
        if self.application and self.running:
            try:
                self.application.stop()
            except:
                pass
            self.running = False
            logger.info("🛑 Bot durduruldu")

    # ============ KOMUTLAR ============
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not await self.check_channels(update, context):
            return
        
        self.register_user(user)
        
        keyboard = [
            [InlineKeyboardButton("🔍 TC Sorgula", callback_data="sorgu_tc")],
            [InlineKeyboardButton("👤 Ad Soyad Sorgula", callback_data="sorgu_adsoyad")],
            [InlineKeyboardButton("📍 Adres Sorgula", callback_data="sorgu_adres")],
            [InlineKeyboardButton("📱 GSM'den TC", callback_data="sorgu_gsmtc")],
            [InlineKeyboardButton("🆔 TC'den GSM", callback_data="sorgu_tcgsm")],
            [InlineKeyboardButton("🏢 İş Yeri Sorgula", callback_data="sorgu_isyeri")],
            [InlineKeyboardButton("👨‍👩‍👧‍👦 Sülale Sorgula", callback_data="sorgu_sulale")],
            [InlineKeyboardButton("📊 İstatistikler", callback_data="istatistik")],
            [InlineKeyboardButton("❓ Yardım", callback_data="yardim")]
        ]
        
        if self.is_admin(user.id):
            keyboard.append([InlineKeyboardButton("🔧 Admin Paneli", callback_data="admin_panel")])
        
        text = f"""
🔍 **HOŞGELDİNİZ!** 🔍

Merhaba {user.first_name}!

Aşağıdaki butonlardan sorgulama yapabilirsiniz.
📋 **KURALLAR:** Günde 50 sorgu limiti

📊 **İSTATİSTİK:**
• Bugün: {self.get_today_queries()}
• Kullanıcı: {self.get_user_count()}
"""
        
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.is_admin(user_id):
            await update.message.reply_text("⛔ Yetkiniz yok!")
            return
        
        keyboard = [
            [InlineKeyboardButton("📊 İstatistikler", callback_data="admin_stats")],
            [InlineKeyboardButton("👥 Kullanıcılar", callback_data="admin_users")],
            [InlineKeyboardButton("🚫 Banlılar", callback_data="admin_bans")],
            [InlineKeyboardButton("📢 Duyuru Gönder", callback_data="admin_announce")],
            [InlineKeyboardButton("🤖 Bot Klonla", callback_data="admin_clone")],
            [InlineKeyboardButton("🔄 Bot Yeniden Başlat", callback_data="admin_restart")],
            [InlineKeyboardButton("🛑 Bot Durdur", callback_data="admin_stop")],
            [InlineKeyboardButton("📈 Sistem Durumu", callback_data="admin_system")],
            [InlineKeyboardButton("🔙 Ana Menü", callback_data="ana_menü")]
        ]
        
        await update.message.reply_text(
            "🔧 **Admin Paneli**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if self.is_admin(user_id):
            try:
                import psutil
                cpu = psutil.cpu_percent()
                ram = psutil.virtual_memory()
                text = f"""
📊 **SİSTEM İSTATİSTİKLERİ**

• Çalışma: {self.get_uptime()}
• Toplam sorgu: {self.get_total_queries()}
• Bugünkü sorgu: {self.get_today_queries()}
• Kullanıcı: {self.get_user_count()}
• Banlı: {self.get_banned_count()}
• Admin: {self.get_admin_count()}
• CPU: {cpu}%
• RAM: {ram.percent}%
"""
            except:
                text = "⚠️ Sistem bilgisi alınamadı"
        else:
            stats = self.get_user_stats(user_id)
            text = f"""
📊 **KİŞİSEL İSTATİSTİKLER**

• Toplam sorgu: {stats['total']}
• Bugünkü sorgu: {stats['today']}
• Durum: {'✅ Aktif' if not self.is_banned(user_id) else '❌ Banlı'}
"""
        
        keyboard = [[InlineKeyboardButton("🔙 Ana Menü", callback_data="ana_menü")]]
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    async def ban_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ Yetkiniz yok!")
            return
        if not context.args:
            await update.message.reply_text("❌ Kullanım: /ban USER_ID SEBEP")
            return
        try:
            target_id = int(context.args[0])
            reason = ' '.join(context.args[1:]) if len(context.args) > 1 else 'Kural ihlali'
            if self.ban_user(target_id, reason):
                await update.message.reply_text(f"✅ Kullanıcı {target_id} banlandı!\nSebep: {reason}")
            else:
                await update.message.reply_text("❌ Ban başarısız!")
        except:
            await update.message.reply_text("❌ Geçersiz ID!")

    async def unban_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ Yetkiniz yok!")
            return
        if not context.args:
            await update.message.reply_text("❌ Kullanım: /unban USER_ID")
            return
        try:
            target_id = int(context.args[0])
            if self.unban_user(target_id):
                await update.message.reply_text(f"✅ Kullanıcı {target_id} banı kaldırıldı!")
            else:
                await update.message.reply_text("❌ Unban başarısız!")
        except:
            await update.message.reply_text("❌ Geçersiz ID!")

    async def announce_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ Yetkiniz yok!")
            return
        if not context.args:
            await update.message.reply_text("❌ Kullanım: /duyuru MESAJ")
            return
        message = ' '.join(context.args)
        await self.send_announcement(update, message)

    async def clone_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ Yetkiniz yok!")
            return
        await self.clone_bot(update)

    async def restart_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text("⛔ Sadece bot sahibi!")
            return
        await update.message.reply_text("🔄 Yeniden başlatılıyor...")
        self.stop()
        time.sleep(2)
        self.start()

    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text("⛔ Sadece bot sahibi!")
            return
        await update.message.reply_text("🛑 Durduruluyor...")
        self.stop()

    # ============ CALLBACK İŞLEMLERİ ============
    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        data = query.data
        
        if self.is_banned(user_id):
            await query.edit_message_text("❌ Banlısınız!")
            return
        
        if not await self.check_channels_callback(update, context):
            return
        
        # Sorgu menüleri
        if data.startswith("sorgu_"):
            sorgu_tipi = data.replace("sorgu_", "")
            self.user_states[user_id] = f"bekle_{sorgu_tipi}"
            
            mesajlar = {
                "tc": "📝 TC kimlik numarasını girin:\nÖrnek: `12345678901`",
                "adsoyad": "📝 Ad, Soyad, İl ve İlçe girin:\nÖrnek: `Ahmet Yılmaz İstanbul Kadıköy`",
                "adres": "📝 TC kimlik numarasını girin:\nÖrnek: `12345678901`",
                "gsmtc": "📝 GSM numarasını girin:\nÖrnek: `5551234567`",
                "tcgsm": "📝 TC kimlik numarasını girin:\nÖrnek: `12345678901`",
                "isyeri": "📝 TC kimlik numarasını girin:\nÖrnek: `12345678901`",
                "sulale": "📝 TC kimlik numarasını girin:\nÖrnek: `12345678901`"
            }
            
            await query.edit_message_text(
                mesajlar.get(sorgu_tipi, "📝 Parametreleri girin:"),
                parse_mode='Markdown'
            )
            
            keyboard = [[InlineKeyboardButton("🔙 Ana Menü", callback_data="ana_menü")]]
            await query.message.reply_text(
                "🔄 İptal etmek için butona tıklayın:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        elif data == "ana_menü":
            await self.start_command(update, context)
            
        elif data == "istatistik":
            await self.stats_command(update, context)
            
        elif data == "yardim":
            help_text = """
📚 **YARDIM MENÜSÜ**

🔍 **Sorgulama Türleri:**
• TC Kimlik Sorgulama
• Ad Soyad Sorgulama
• Adres Sorgulama
• GSM'den TC Bulma
• TC'den GSM Bulma
• İş Yeri Sorgulama
• Sülale Sorgulama

📋 **KURALLAR:**
• Günde 50 sorgu
• Yasaklı kelimeler engelli
• Spam yapmayın

👑 **Adminler İçin:**
• /admin - Admin paneli
• /ban - Kullanıcı banla
• /unban - Ban kaldır
• /duyuru - Duyuru gönder
"""
            await query.edit_message_text(help_text, parse_mode='Markdown')
            keyboard = [[InlineKeyboardButton("🔙 Ana Menü", callback_data="ana_menü")]]
            await query.message.reply_text(
                "Ana menüye dönmek için:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        elif data == "admin_panel":
            if not self.is_admin(user_id):
                await query.edit_message_text("⛔ Yetkiniz yok!")
                return
            await self.admin_command(update, context)
            
        # Admin işlemleri
        elif data == "admin_stats":
            await self.stats_command(update, context)
        elif data == "admin_users":
            await self.show_users(query)
        elif data == "admin_bans":
            await self.show_bans(query)
        elif data == "admin_announce":
            await query.edit_message_text("📢 Duyuru mesajını girin:")
            self.user_states[user_id] = "bekle_duyuru"
        elif data == "admin_clone":
            await self.clone_bot(query, True)
        elif data == "admin_restart":
            await query.edit_message_text("🔄 Yeniden başlatılıyor...")
            self.stop()
            time.sleep(2)
            self.start()
        elif data == "admin_stop":
            await query.edit_message_text("🛑 Durduruluyor...")
            self.stop()
        elif data == "admin_system":
            await self.show_system(query)

    # ============ MESAJ İŞLEME ============
    async def message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        text = update.message.text
        
        if self.is_banned(user_id):
            await update.message.reply_text("❌ Banlısınız!")
            return
        
        if not await self.check_channels(update, context):
            return
        
        # Yasaklı kelime kontrolü
        for word in BANNED_WORDS:
            if word.lower() in text.lower():
                self.ban_user(user_id, f"Yasaklı kelime: {word}")
                await update.message.reply_text("⚠️ Yasaklı kelime kullanımı nedeniyle banlandınız!")
                return
        
        # Kullanıcı durumu kontrolü
        if user_id in self.user_states:
            state = self.user_states[user_id]
            
            if state.startswith("bekle_"):
                sorgu_tipi = state.replace("bekle_", "")
                await self.process_query(update, sorgu_tipi, text)
                del self.user_states[user_id]
                return
            
            elif state == "bekle_duyuru":
                if self.is_admin(user_id):
                    await self.send_announcement(update, text)
                del self.user_states[user_id]
                return
        
        # Normal mesaj - Ana menüye yönlendir
        await self.start_command(update, context)

    # ============ SORGU İŞLEME ============
    async def process_query(self, update: Update, q_type: str, q_param: str):
        user_id = update.effective_user.id
        
        # Rate limit
        if user_id in self.rate_limits:
            if time.time() - self.rate_limits[user_id] < 5:
                await update.message.reply_text("⏳ Lütfen 5 saniye bekleyin!")
                return
        self.rate_limits[user_id] = time.time()
        
        # Günlük limit
        if self.get_user_today_queries(user_id) >= 50:
            await update.message.reply_text("⚠️ Günlük sorgu limitine ulaştınız! (50)")
            return
        
        # Parametre doğrulama
        if q_type in ["tc", "adres", "tcgsm", "isyeri", "sulale"]:
            if not self.validate_tc(q_param):
                await update.message.reply_text("❌ Geçersiz TC kimlik numarası!")
                return
        elif q_type == "gsmtc":
            if not self.validate_gsm(q_param):
                await update.message.reply_text("❌ Geçersiz GSM numarası!")
                return
        
        # API URL oluştur
        if q_type == "tc":
            url = APIS["tc"].format(q_param)
        elif q_type == "adsoyad":
            params = q_param.split(' ')
            if len(params) < 4:
                await update.message.reply_text("❌ Format: Ad Soyad İl İlçe")
                return
            url = APIS["adsoyad"].format(params[0], params[1], params[2], ' '.join(params[3:]))
        elif q_type == "adres":
            url = APIS["adres"].format(q_param)
        elif q_type == "gsmtc":
            url = APIS["gsmtc"].format(q_param)
        elif q_type == "tcgsm":
            url = APIS["tcgsm"].format(q_param)
        elif q_type == "isyeri":
            url = APIS["isyeri"].format(q_param)
        elif q_type == "sulale":
            url = APIS["sulale"].format(q_param)
        else:
            await update.message.reply_text("❌ Geçersiz sorgu tipi!")
            return
        
        try:
            await update.message.reply_text("⏳ Sorgulanıyor... (Cloudflare bypass aktif)")
            
            # Cloudflare bypass
            response = scraper.get(url, timeout=30)
            data = response.text
            
            # Cloudflare kontrolü
            if "Just a moment..." in data or "cf_chl" in data:
                await update.message.reply_text("⚠️ Cloudflare koruması aşılamıyor! Lütfen daha sonra tekrar deneyin.")
                return
            
            # Dosya oluştur
            filename = f"sorgu_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            formatted = f"""
==========================================
🔍 SORGULAMA SONUCU
==========================================
Tip: {q_type.upper()}
Parametre: {q_param}
Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
==========================================

{data}

==========================================
✅ Sorgu tamamlandı!
==========================================
"""
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(formatted)
            
            with open(filename, 'rb') as f:
                await update.message.reply_document(f, filename=filename)
            
            self.save_query(user_id, q_type, q_param)
            os.remove(filename)
            
            # Ana menü butonu
            keyboard = [[InlineKeyboardButton("🔙 Ana Menü", callback_data="ana_menü")]]
            await update.message.reply_text(
                "✅ Sorgu tamamlandı!",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        except Exception as e:
            logger.error(f"Sorgu hatası: {e}")
            await update.message.reply_text(f"❌ Hata: {str(e)}")

    # ============ YARDIMCI FONKSİYONLAR ============
    def register_user(self, user):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, join_date, last_active) VALUES (?, ?, ?, ?, ?)",
                      (user.id, user.username, user.first_name, datetime.now().isoformat(), datetime.now().isoformat()))
            c.execute("UPDATE users SET last_active = ? WHERE user_id = ?", (datetime.now().isoformat(), user.id))
            conn.commit()
            conn.close()
        except:
            pass

    def is_admin(self, user_id):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
            result = c.fetchone()
            conn.close()
            return result is not None
        except:
            return False

    def is_banned(self, user_id):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT 1 FROM bans WHERE user_id = ?", (user_id,))
            result = c.fetchone()
            conn.close()
            return result is not None
        except:
            return False

    def ban_user(self, user_id, reason):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO bans (user_id, reason, ban_date) VALUES (?, ?, ?)",
                      (user_id, reason, datetime.now().isoformat()))
            c.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
            return True
        except:
            return False

    def unban_user(self, user_id):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM bans WHERE user_id = ?", (user_id,))
            c.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
            return True
        except:
            return False

    def save_query(self, user_id, q_type, q_param):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("INSERT INTO queries (user_id, query_type, query_param, query_time) VALUES (?, ?, ?, ?)",
                      (user_id, q_type, q_param, datetime.now().isoformat()))
            c.execute("UPDATE users SET query_count = query_count + 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
        except:
            pass

    def validate_tc(self, tc):
        if not tc.isdigit() or len(tc) != 11:
            return False
        return True

    def validate_gsm(self, gsm):
        gsm = re.sub(r'\D', '', gsm)
        return len(gsm) >= 10 and len(gsm) <= 11

    async def check_channels(self, update, context):
        try:
            user_id = update.effective_user.id
            for channel in REQUIRED_CHANNELS:
                try:
                    member = await context.bot.get_chat_member(channel, user_id)
                    if member.status not in ['member', 'administrator', 'creator']:
                        await update.message.reply_text(f"❌ {channel} kanalına katılın!")
                        return False
                except:
                    continue
            return True
        except:
            return True

    async def check_channels_callback(self, update, context):
        try:
            user_id = update.effective_user.id
            for channel in REQUIRED_CHANNELS:
                try:
                    member = await context.bot.get_chat_member(channel, user_id)
                    if member.status not in ['member', 'administrator', 'creator']:
                        await update.edit_message_text(f"❌ {channel} kanalına katılın!")
                        return False
                except:
                    continue
            return True
        except:
            return True

    async def send_announcement(self, update, message):
        users = self.get_all_users()
        sent = 0
        for user_id in users:
            try:
                await update.message.reply_text(
                    f"📢 **DUYURU**\n\n{message}",
                    parse_mode='Markdown'
                )
                sent += 1
                time.sleep(0.05)
            except:
                continue
        await update.message.reply_text(f"✅ Duyuru {sent} kullanıcıya gönderildi!")

    async def clone_bot(self, update, is_callback=False):
        try:
            with open(__file__, 'r', encoding='utf-8') as f:
                content = f.read()
            
            content = re.sub(r'BOT_TOKEN = ".*?"', 'BOT_TOKEN = "YOUR_TOKEN_HERE"', content)
            content = re.sub(r'OWNER_ID = \d+', 'OWNER_ID = 0', content)
            
            filename = f"cloned_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(content)
            
            msg = f"✅ **Klonlandı!**\nDosya: {filename}"
            
            if is_callback:
                await update.edit_message_text(msg, parse_mode='Markdown')
            else:
                await update.message.reply_text(msg, parse_mode='Markdown')
            
            with open(filename, 'rb') as f:
                if is_callback:
                    await update.message.reply_document(f)
                else:
                    await update.message.reply_document(f)
            
            os.remove(filename)
        except Exception as e:
            error = f"❌ Hata: {str(e)}"
            if is_callback:
                await update.edit_message_text(error)
            else:
                await update.message.reply_text(error)

    # ============ ADMIN GÖSTERİMLERİ ============
    async def show_users(self, query):
        users = self.get_users_list()
        if not users:
            await query.edit_message_text("📭 Kullanıcı yok")
            return
        text = "👥 **KULLANICILAR**\n\n"
        for i, u in enumerate(users[:20], 1):
            text += f"{i}. ID: `{u[0]}` | @{u[1] or 'yok'} | Sorgu: {u[2]}\n"
        
        keyboard = [[InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    async def show_bans(self, query):
        bans = self.get_bans_list()
        if not bans:
            await query.edit_message_text("📭 Banlı kullanıcı yok")
            return
        text = "🚫 **BANLI KULLANICILAR**\n\n"
        for i, b in enumerate(bans[:20], 1):
            text += f"{i}. ID: `{b[0]}` | Sebep: {b[1]} | Tarih: {b[2]}\n"
        
        keyboard = [[InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    async def show_system(self, query):
        try:
            import psutil
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            text = f"""
📈 **SİSTEM DURUMU**

CPU: {cpu}%
RAM: {ram.percent}% ({ram.used / (1024**3):.2f} GB / {ram.total / (1024**3):.2f} GB)
Disk: {disk.percent}% ({disk.used / (1024**3):.2f} GB / {disk.total / (1024**3):.2f} GB)
Çalışma: {self.get_uptime()}
"""
            keyboard = [[InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        except:
            await query.edit_message_text("❌ Sistem bilgisi alınamadı")

    # ============ VERİTABANI SORGULARI ============
    def get_user_count(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM users")
            count = c.fetchone()[0]
            conn.close()
            return count
        except:
            return 0

    def get_banned_count(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM bans")
            count = c.fetchone()[0]
            conn.close()
            return count
        except:
            return 0

    def get_admin_count(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM admins")
            count = c.fetchone()[0]
            conn.close()
            return count
        except:
            return 0

    def get_total_queries(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM queries")
            count = c.fetchone()[0]
            conn.close()
            return count
        except:
            return 0

    def get_today_queries(self):
        try:
            today = datetime.now().date().isoformat()
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM queries WHERE date(query_time) = ?", (today,))
            count = c.fetchone()[0]
            conn.close()
            return count
        except:
            return 0

    def get_user_today_queries(self, user_id):
        try:
            today = datetime.now().date().isoformat()
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM queries WHERE user_id = ? AND date(query_time) = ?", (user_id, today))
            count = c.fetchone()[0]
            conn.close()
            return count
        except:
            return 0

    def get_user_stats(self, user_id):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM queries WHERE user_id = ?", (user_id,))
            total = c.fetchone()[0]
            today = datetime.now().date().isoformat()
            c.execute("SELECT COUNT(*) FROM queries WHERE user_id = ? AND date(query_time) = ?", (user_id, today))
            today_count = c.fetchone()[0]
            conn.close()
            return {'total': total, 'today': today_count}
        except:
            return {'total': 0, 'today': 0}

    def get_users_list(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT user_id, username, query_count FROM users ORDER BY query_count DESC LIMIT 20")
            users = c.fetchall()
            conn.close()
            return users
        except:
            return []

    def get_bans_list(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT user_id, reason, ban_date FROM bans ORDER BY ban_date DESC LIMIT 20")
            bans = c.fetchall()
            conn.close()
            return bans
        except:
            return []

    def get_all_users(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT user_id FROM users")
            users = [row[0] for row in c.fetchall()]
            conn.close()
            return users
        except:
            return []

    def get_uptime(self):
        if not self.running:
            return "Çalışmıyor"
        delta = datetime.now() - self.start_time
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        return f"{delta.days}g {hours}s {minutes}d"

# ============ ANA ÇALIŞTIRMA ============
def main():
    try:
        print("🚀 Bot başlatılıyor...")
        bot = BotSystem()
        bot.start()
    except KeyboardInterrupt:
        print("\n🛑 Durduruldu")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Hata: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
