# bot.py - Ana Bot Dosyası (Render Uyumlu)
import os
import re
import json
import sqlite3
import requests
import subprocess
import sys
import time
import logging
from datetime import datetime
from typing import Dict, List, Tuple

# Telegram kütüphanesi yüklemesi
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

# Zorunlu Kanallar
REQUIRED_CHANNELS = ["@iosstarturkiyee", "@rinexsorgux", "@izinsizleriz"]

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

# Yasaklı Kelimeler
BANNED_WORDS = ["#404", "#banned", "#kurucu", "#team", "#telegram"]

# Logging
logging.basicConfig(level=logging.INFO)
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
    c.execute('''CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY
    )''')
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

init_db()

# ============ BOT SINIFI ============
class BotSystem:
    def __init__(self):
        self.app = None
        self.running = False
        self.start_time = datetime.now()
        self.rate_limits = {}

    def start(self):
        try:
            logger.info("🚀 Bot başlatılıyor...")
            self.app = Application.builder().token(BOT_TOKEN).build()
            
            # Komutlar
            self.app.add_handler(CommandHandler("start", self.start_cmd))
            self.app.add_handler(CommandHandler("admin", self.admin_cmd))
            self.app.add_handler(CommandHandler("stats", self.stats_cmd))
            self.app.add_handler(CommandHandler("ban", self.ban_cmd))
            self.app.add_handler(CommandHandler("unban", self.unban_cmd))
            self.app.add_handler(CommandHandler("duyuru", self.announce_cmd))
            self.app.add_handler(CommandHandler("clone", self.clone_cmd))
            self.app.add_handler(CommandHandler("restart", self.restart_cmd))
            self.app.add_handler(CommandHandler("stop", self.stop_cmd))
            
            # Callback ve mesaj
            self.app.add_handler(CallbackQueryHandler(self.callback_handler))
            self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.message_handler))
            
            self.running = True
            self.app.run_polling()
        except Exception as e:
            logger.error(f"Hata: {e}")
            self.running = False

    def stop(self):
        if self.app and self.running:
            self.app.stop()
            self.running = False
            logger.info("Bot durduruldu")

    # ============ KOMUTLAR ============
    async def start_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not await self.check_channels(update, context):
            return
        
        self.register_user(user)
        
        text = f"""
🔍 **HOŞGELDİNİZ!** 🔍

Merhaba {user.first_name}!

📋 **KULLANIM:**
• `tc 12345678901`
• `adsoyad Ad Soyad İl İlçe`
• `adres 12345678901`
• `gsmtc 5551234567`
• `tcgsm 12345678901`
• `isyeri 12345678901`
• `sulale 12345678901`

⚠️ **KURALLAR:**
• Günde 50 sorgu limiti
• Yasaklı kelimeler: #404, #banned, #kurucu, #team, #telegram
• 3 kanala üyelik zorunlu

📊 **İSTATİSTİK:**
• Toplam sorgu: {self.get_total_queries()}
• Bugün: {self.get_today_queries()}
• Kullanıcı: {self.get_user_count()}
"""
        await update.message.reply_text(text, parse_mode='Markdown')

    async def admin_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.is_admin(user_id):
            await update.message.reply_text("⛔ Yetkiniz yok!")
            return
        
        keyboard = [
            [InlineKeyboardButton("📊 İstatistik", callback_data="stats")],
            [InlineKeyboardButton("👥 Kullanıcılar", callback_data="users")],
            [InlineKeyboardButton("🚫 Ban Yönetimi", callback_data="ban")],
            [InlineKeyboardButton("📢 Duyuru", callback_data="announce")],
            [InlineKeyboardButton("🤖 Klonla", callback_data="clone")],
            [InlineKeyboardButton("🔄 Yeniden Başlat", callback_data="restart")],
            [InlineKeyboardButton("🛑 Durdur", callback_data="stop")],
            [InlineKeyboardButton("📈 Sistem", callback_data="system")]
        ]
        await update.message.reply_text("🔧 **Admin Paneli**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    async def stats_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if self.is_admin(user_id):
            text = f"""
📊 **SİSTEM İSTATİSTİKLERİ**

• Çalışma: {self.get_uptime()}
• Toplam sorgu: {self.get_total_queries()}
• Bugünkü sorgu: {self.get_today_queries()}
• Kullanıcı: {self.get_user_count()}
• Banlı: {self.get_banned_count()}
• Admin: {self.get_admin_count()}
"""
        else:
            stats = self.get_user_stats(user_id)
            text = f"""
📊 **KİŞİSEL İSTATİSTİKLER**

• Toplam sorgu: {stats['total']}
• Bugünkü sorgu: {stats['today']}
• Durum: {'✅ Aktif' if not self.is_banned(user_id) else '❌ Banlı'}
"""
        await update.message.reply_text(text, parse_mode='Markdown')

    async def ban_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ Yetkiniz yok!")
            return
        if not context.args:
            await update.message.reply_text("❌ Kullanım: /ban USER_ID SEBEP")
            return
        target_id = int(context.args[0])
        reason = ' '.join(context.args[1:]) if len(context.args) > 1 else 'Kural ihlali'
        if self.ban_user(target_id, reason):
            await update.message.reply_text(f"✅ Kullanıcı {target_id} banlandı!\nSebep: {reason}")
        else:
            await update.message.reply_text("❌ Ban başarısız!")

    async def unban_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ Yetkiniz yok!")
            return
        if not context.args:
            await update.message.reply_text("❌ Kullanım: /unban USER_ID")
            return
        target_id = int(context.args[0])
        if self.unban_user(target_id):
            await update.message.reply_text(f"✅ Kullanıcı {target_id} banı kaldırıldı!")
        else:
            await update.message.reply_text("❌ Unban başarısız!")

    async def announce_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ Yetkiniz yok!")
            return
        if not context.args:
            await update.message.reply_text("❌ Kullanım: /duyuru MESAJ")
            return
        message = ' '.join(context.args)
        users = self.get_all_users()
        sent = 0
        for user_id in users:
            try:
                await context.bot.send_message(user_id, f"📢 **DUYURU**\n\n{message}", parse_mode='Markdown')
                sent += 1
                time.sleep(0.1)
            except:
                continue
        await update.message.reply_text(f"✅ Duyuru {sent} kullanıcıya gönderildi!")

    async def clone_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ Yetkiniz yok!")
            return
        await self.clone_bot(update)

    async def restart_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text("⛔ Sadece bot sahibi!")
            return
        await update.message.reply_text("🔄 Yeniden başlatılıyor...")
        self.stop()
        time.sleep(2)
        self.start()

    async def stop_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text("⛔ Sadece bot sahibi!")
            return
        await update.message.reply_text("🛑 Durduruluyor...")
        self.stop()

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
        
        await self.process_query(update, text)

    async def process_query(self, update: Update, text: str):
        parts = text.split(' ', 1)
        if len(parts) < 2:
            await update.message.reply_text("❌ Format: `tip parametre`\nÖrnek: `tc 12345678901`")
            return
        
        q_type, q_param = parts[0].lower(), parts[1].strip()
        
        # API seçimi
        if q_type == "tc":
            if not self.validate_tc(q_param):
                await update.message.reply_text("❌ Geçersiz TC!")
                return
            url = APIS["tc"].format(q_param)
        elif q_type == "adsoyad":
            params = q_param.split(' ')
            if len(params) < 4:
                await update.message.reply_text("❌ Format: `adsoyad AD SOYAD İL İLÇE`")
                return
            url = APIS["adsoyad"].format(params[0], params[1], params[2], ' '.join(params[3:]))
        elif q_type == "adres":
            if not self.validate_tc(q_param):
                await update.message.reply_text("❌ Geçersiz TC!")
                return
            url = APIS["adres"].format(q_param)
        elif q_type == "gsmtc":
            url = APIS["gsmtc"].format(q_param)
        elif q_type == "tcgsm":
            if not self.validate_tc(q_param):
                await update.message.reply_text("❌ Geçersiz TC!")
                return
            url = APIS["tcgsm"].format(q_param)
        elif q_type == "isyeri":
            if not self.validate_tc(q_param):
                await update.message.reply_text("❌ Geçersiz TC!")
                return
            url = APIS["isyeri"].format(q_param)
        elif q_type == "sulale":
            if not self.validate_tc(q_param):
                await update.message.reply_text("❌ Geçersiz TC!")
                return
            url = APIS["sulale"].format(q_param)
        else:
            await update.message.reply_text("❌ Desteklenen: tc, adsoyad, adres, gsmtc, tcgsm, isyeri, sulale")
            return
        
        try:
            await update.message.reply_text("⏳ Sorgulanıyor...")
            response = requests.get(url, timeout=10)
            data = response.text
            
            # Dosya oluştur
            filename = f"query_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
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
            
            self.save_query(update.effective_user.id, q_type, q_param)
            os.remove(filename)
            
        except Exception as e:
            await update.message.reply_text(f"❌ Hata: {str(e)}")

    # ============ CALLBACK ============
    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        if not self.is_admin(user_id):
            await query.edit_message_text("⛔ Yetkiniz yok!")
            return
        
        data = query.data
        if data == "stats":
            await self.stats_cmd(update, context)
        elif data == "users":
            users = self.get_users_list()
            text = "👥 **KULLANICILAR**\n\n"
            for i, u in enumerate(users[:20], 1):
                text += f"{i}. ID: `{u[0]}` | @{u[1] or 'yok'} | Sorgu: {u[2]}\n"
            await query.edit_message_text(text, parse_mode='Markdown')
        elif data == "ban":
            await query.edit_message_text("🚫 **BAN YÖNETİMİ**\n\n/ban USER_ID SEBEP\n/unban USER_ID", parse_mode='Markdown')
        elif data == "announce":
            await query.edit_message_text("📢 **DUYURU**\n\n/duyuru MESAJ", parse_mode='Markdown')
        elif data == "clone":
            await self.clone_bot(query, True)
        elif data == "restart":
            await query.edit_message_text("🔄 Yeniden başlatılıyor...")
            self.stop()
            time.sleep(2)
            self.start()
            await query.edit_message_text("✅ Yeniden başlatıldı!")
        elif data == "stop":
            await query.edit_message_text("🛑 Durduruluyor...")
            self.stop()
        elif data == "system":
            import psutil
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory()
            text = f"""
📈 **SİSTEM DURUMU**

CPU: {cpu}%
RAM: {ram.percent}%
RAM Kullanım: {ram.used / (1024**3):.2f} GB
RAM Toplam: {ram.total / (1024**3):.2f} GB
Çalışma: {self.get_uptime()}
"""
            await query.edit_message_text(text, parse_mode='Markdown')

    # ============ YARDIMCI FONKSİYONLAR ============
    def register_user(self, user):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, join_date, last_active) VALUES (?, ?, ?, ?, ?)",
                  (user.id, user.username, user.first_name, datetime.now().isoformat(), datetime.now().isoformat()))
        c.execute("UPDATE users SET last_active = ? WHERE user_id = ?", (datetime.now().isoformat(), user.id))
        conn.commit()
        conn.close()

    def is_admin(self, user_id):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        conn.close()
        return result is not None

    def is_banned(self, user_id):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT 1 FROM bans WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        conn.close()
        return result is not None

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
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO queries (user_id, query_type, query_param, query_time) VALUES (?, ?, ?, ?)",
                  (user_id, q_type, q_param, datetime.now().isoformat()))
        c.execute("UPDATE users SET query_count = query_count + 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

    def validate_tc(self, tc):
        if not tc.isdigit() or len(tc) != 11:
            return False
        return True

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

    # ============ VERİTABANI SORGULARI ============
    def get_user_count(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        count = c.fetchone()[0]
        conn.close()
        return count

    def get_banned_count(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM bans")
        count = c.fetchone()[0]
        conn.close()
        return count

    def get_admin_count(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM admins")
        count = c.fetchone()[0]
        conn.close()
        return count

    def get_total_queries(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM queries")
        count = c.fetchone()[0]
        conn.close()
        return count

    def get_today_queries(self):
        today = datetime.now().date().isoformat()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM queries WHERE date(query_time) = ?", (today,))
        count = c.fetchone()[0]
        conn.close()
        return count

    def get_user_today_queries(self, user_id):
        today = datetime.now().date().isoformat()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM queries WHERE user_id = ? AND date(query_time) = ?", (user_id, today))
        count = c.fetchone()[0]
        conn.close()
        return count

    def get_user_stats(self, user_id):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM queries WHERE user_id = ?", (user_id,))
        total = c.fetchone()[0]
        today = datetime.now().date().isoformat()
        c.execute("SELECT COUNT(*) FROM queries WHERE user_id = ? AND date(query_time) = ?", (user_id, today))
        today_count = c.fetchone()[0]
        conn.close()
        return {'total': total, 'today': today_count}

    def get_users_list(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id, username, query_count FROM users ORDER BY query_count DESC LIMIT 20")
        users = c.fetchall()
        conn.close()
        return users

    def get_all_users(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id FROM users")
        users = [row[0] for row in c.fetchall()]
        conn.close()
        return users

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
        # Gerekli paketler
        for pkg in ["python-telegram-bot", "requests", "psutil"]:
            try:
                __import__(pkg.split('-')[0])
            except:
                subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
        
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
