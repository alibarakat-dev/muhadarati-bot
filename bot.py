# -*- coding: utf-8 -*-
"""
بوت محاضرات المعلوماتية - جامعة الوادي الخاصة
python-telegram-bot v21 + SQLite
"""
import os
import re
import sqlite3
import asyncio
import logging
import time
import json
import html
from urllib.parse import quote, unquote

import httpx
from collections import defaultdict, deque
from datetime import datetime

from dotenv import load_dotenv
from telegram import Update, BotCommand, InputFile, InlineKeyboardButton as B, InlineKeyboardMarkup as M
from telegram.error import Forbidden, BadRequest, RetryAfter
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, ContextTypes, filters)

load_dotenv()
TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])
DB_PATH = os.getenv("DB_PATH", "bot.db")
YEARS = int(os.getenv("YEARS", "5"))

# مزامنة موقع الجامعة
SITE = os.getenv("SITE_URL", "https://wiu.edu.sy").rstrip("/")
FACULTY = os.getenv("FACULTY_ID", "4")                    # 4 = الهندسة المعلوماتية
SYNC_MIN = int(os.getenv("SYNC_MINUTES", "30"))           # 0 = إيقاف المزامنة التلقائية
STORAGE_CHAT = int(os.getenv("STORAGE_CHAT_ID") or OWNER_ID)  # قناة خاصة لتخزين الملفات
AUTO_NOTIFY = os.getenv("AUTO_NOTIFY", "1") == "1"

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)  # حتى ما ينطبع التوكن باللوغ
log = logging.getLogger("bot")

CATS = {"th": "📘 نظري", "pr": "💻 عملي", "ex": "📝 أسئلة دورات", "su": "📄 ملخصات"}
YEAR_NAMES = ["الأولى", "الثانية", "الثالثة", "الرابعة", "الخامسة", "السادسة"]
SEM_NAMES = {1: "الفصل الأول", 2: "الفصل الثاني"}


# ---------------------------- قاعدة البيانات ----------------------------
def norm(t):
    """توحيد الأحرف العربية للبحث"""
    if t is None:
        return ""
    t = t.lower()
    t = re.sub("[أإآ]", "ا", t)
    t = t.replace("ة", "ه").replace("ى", "ي").replace("ـ", "")
    t = re.sub("[\u064B-\u0652]", "", t)  # حذف التشكيل
    return t


db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db.create_function("norm", 1, norm)
db.executescript("""
CREATE TABLE IF NOT EXISTS subjects(
    id INTEGER PRIMARY KEY, year INT, sem INT, name TEXT, UNIQUE(year, sem, name));
CREATE TABLE IF NOT EXISTS files(
    id INTEGER PRIMARY KEY, subject_id INT, cat TEXT, title TEXT,
    file_id TEXT, kind TEXT, added_at TEXT);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, username TEXT, joined TEXT);
CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS banned(id INTEGER PRIMARY KEY);
CREATE INDEX IF NOT EXISTS idx_files ON files(subject_id, cat);
CREATE TABLE IF NOT EXISTS synced(code TEXT, fname TEXT, PRIMARY KEY(code, fname));
""")


def q(sql, *a):
    return db.execute(sql, a).fetchall()


def x(sql, *a):
    cur = db.execute(sql, a)
    db.commit()
    return cur.lastrowid


if "code" not in [r["name"] for r in q("PRAGMA table_info(subjects)")]:
    x("ALTER TABLE subjects ADD COLUMN code TEXT")
x("CREATE UNIQUE INDEX IF NOT EXISTS idx_code ON subjects(code)")


def is_admin(uid):
    return uid == OWNER_ID or bool(q("SELECT 1 FROM admins WHERE id=?", uid))


# ---------------------------- الحماية ----------------------------
ALLOWED_EXT = (".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".zip", ".rar")
_hits = defaultdict(deque)
_bulk = {}


def is_banned(uid):
    return bool(q("SELECT 1 FROM banned WHERE id=?", uid))


def rate_ok(uid, limit=20, window=10):
    """حد أقصى 20 ضغطة كل 10 ثواني لكل مستخدم (ضد السبام)"""
    if is_admin(uid):
        return True
    now = time.monotonic()
    dq = _hits[uid]
    while dq and now - dq[0] > window:
        dq.popleft()
    if len(dq) >= limit:
        return False
    dq.append(now)
    return True


def bulk_ok(uid, cooldown=30):
    """زر «إرسال الكل» مرة كل 30 ثانية"""
    if is_admin(uid):
        return True
    now = time.monotonic()
    if now - _bulk.get(uid, 0) < cooldown:
        return False
    _bulk[uid] = now
    return True


def to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def subj(sid):
    r = q("SELECT * FROM subjects WHERE id=?", sid)
    return r[0] if r else None


def place_name(sid, cat):
    if cat == "sched":
        return "📅 البرنامج الامتحاني"
    s = subj(sid)
    return f"{s['name']} ← {CATS[cat]}" if s else "?"


def yname(y):
    return YEAR_NAMES[y - 1] if y <= len(YEAR_NAMES) else str(y)


# ---------------------------- الكيبوردات ----------------------------
def years_rows(prefix):
    rows, row = [], []
    for y in range(1, YEARS + 1):
        row.append(B(f"🎓 السنة {yname(y)}", callback_data=f"{prefix}:{y}"))
        if len(row) == 2:
            rows.append(row[::-1])   # من اليمين لليسار
            row = []
    if row:
        rows.append(row)
    return rows


def main_menu():
    rows = years_rows("y")
    rows.append([B("📅 البرنامج الامتحاني", callback_data="sched")])
    rows.append([B("🔍 بحث عن مادة", callback_data="searchhelp")])
    return M(rows)


def upload_menu(ctx):
    rows = []
    last = ctx.user_data.get("last")
    if last:
        rows.append([B(f"📌 نفس المكان: {place_name(*last)}"[:60], callback_data="ulast")])
    rows += years_rows("uy")
    rows.append([B("📅 برنامج امتحاني", callback_data="usched")])
    rows.append([B("❌ إلغاء", callback_data="ucancel")])
    return M(rows)


def cats_kb(sid, prefix, back):
    rows = []
    for k, v in CATS.items():
        n = q("SELECT COUNT(*) c FROM files WHERE subject_id=? AND cat=?", sid, k)[0]["c"]
        label = f"{v} ({n})" if prefix == "cat" else v
        rows.append([B(label, callback_data=f"{prefix}:{sid}:{k}")])
    rows.append([B("🔙 رجوع", callback_data=back)])
    return M(rows)


# ---------------------------- أدوات ----------------------------
async def safe_edit(qy, text, markup=None):
    try:
        await qy.edit_message_text(text, reply_markup=markup)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            await qy.message.reply_text(text, reply_markup=markup)


async def send_file(bot, chat_id, row, admin):
    markup = M([[B("🗑 حذف الملف", callback_data=f"del:{row['id']}")]]) if admin else None
    cap = row["title"][:1000]
    if row["kind"] == "photo":
        await bot.send_photo(chat_id, row["file_id"], caption=cap, reply_markup=markup)
    elif row["kind"] == "video":
        await bot.send_video(chat_id, row["file_id"], caption=cap, reply_markup=markup)
    else:
        await bot.send_document(chat_id, row["file_id"], caption=cap, reply_markup=markup)


async def broadcast(bot, text, markup=None):
    ok = fail = 0
    for r in q("SELECT id FROM users"):
        try:
            await bot.send_message(r["id"], text, reply_markup=markup)
            ok += 1
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await bot.send_message(r["id"], text, reply_markup=markup)
                ok += 1
            except Exception:
                fail += 1
        except Forbidden:
            x("DELETE FROM users WHERE id=?", r["id"])
            fail += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    return ok, fail


def save_queue(ctx, sid, cat):
    queue = ctx.user_data.pop("queue", [])
    now = datetime.now().isoformat(timespec="seconds")
    for fid, kind, title in queue:
        x("INSERT INTO files(subject_id,cat,title,file_id,kind,added_at) VALUES(?,?,?,?,?,?)",
          sid, cat, title, fid, kind, now)
    ctx.user_data["last"] = (sid, cat)
    return len(queue)


def saved_kb(sid, cat):
    return M([[B("🔔 أبلغ الطلاب", callback_data=f"notify:{sid}:{cat}")]])


# ---------------------------- أوامر ----------------------------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if is_banned(u.id):
        return
    x("INSERT OR IGNORE INTO users(id,name,username,joined) VALUES(?,?,?,?)",
      u.id, u.full_name, u.username, datetime.now().isoformat(timespec="seconds"))
    await update.message.reply_text(
        f"أهلاً {u.first_name} 👋\n"
        "بوت محاضرات المعلوماتية – جامعة الوادي الخاصة 💻\n\n"
        "اختار سنتك الدراسية، أو اكتب اسم المادة مباشرة للبحث 👇",
        reply_markup=main_menu())


async def admin_cmd(update: Update, ctx):
    if not is_admin(update.effective_user.id):
        return
    users = q("SELECT COUNT(*) c FROM users")[0]["c"]
    files = q("SELECT COUNT(*) c FROM files")[0]["c"]
    subs = q("SELECT COUNT(*) c FROM subjects")[0]["c"]
    await update.message.reply_text(
        f"🛠 <b>لوحة المشرف</b>\n\n"
        f"👥 المستخدمين: <b>{users}</b>\n"
        f"📚 المواد: <b>{subs}</b>\n"
        f"📁 الملفات: <b>{files}</b>\n\n"
        "<b>📤 رفع الملفات</b>\n"
        "ابعت أو حوّل الملفات للبوت واختار المكان\n\n"
        "<b>🌐 موقع الجامعة</b>\n"
        "جيب أكواد المواد: /discover\n"
        "اربط مادة: /addcourse\n"
        "المواد المربوطة: /courses\n"
        "وقف مزامنة مادة: /delcourse\n"
        f"اسحب الجديد هلق: /sync\n"
        f"(المزامنة التلقائية كل {SYNC_MIN} دقيقة)\n\n"
        "<b>📚 المواد</b>\n"
        "عرض المواد وأرقامها: /subjects\n"
        "تعديل اسم مادة: /renamesub\n"
        "حذف مادة: /delsub\n\n"
        "<b>👥 المستخدمين</b>\n"
        "رسالة لكل الطلاب: /broadcast\n"
        "حظر / فك حظر: /ban  /unban\n"
        "إضافة / حذف مشرف: /addadmin  /deladmin\n\n"
        "إلغاء أي عملية: /cancel\n\n"
        "💡 أي أمر بتبعتو بدون تفاصيل بيقلك كيف تستخدمو",
        parse_mode="HTML")


async def addadmin(update: Update, ctx):
    if update.effective_user.id != OWNER_ID:
        return
    if not ctx.args:
        return await update.message.reply_text("الاستخدام: /addadmin ID\nمثال: /addadmin 123456789")
    uid = to_int(ctx.args[0])
    if uid is None:
        return await update.message.reply_text("ID غلط")
    x("INSERT OR IGNORE INTO admins(id) VALUES(?)", uid)
    await update.message.reply_text("✅ تمت إضافة المشرف")


async def deladmin(update: Update, ctx):
    if update.effective_user.id != OWNER_ID:
        return
    if not ctx.args:
        return await update.message.reply_text("الاستخدام: /deladmin ID")
    x("DELETE FROM admins WHERE id=?", to_int(ctx.args[0]))
    await update.message.reply_text("✅ تم حذف المشرف")


async def broadcast_cmd(update: Update, ctx):
    if not is_admin(update.effective_user.id):
        return
    text = update.message.text.partition(" ")[2].strip()
    if not text:
        await update.message.reply_text("الاستخدام: /broadcast نص الرسالة")
        return
    await update.message.reply_text("⏳ جاري الإرسال...")
    ok, fail = await broadcast(ctx.bot, text)
    await update.message.reply_text(f"✅ وصلت لـ {ok} | ❌ فشلت {fail}")


async def subjects_cmd(update: Update, ctx):
    if not is_admin(update.effective_user.id):
        return
    rows = q("SELECT * FROM subjects ORDER BY year, sem, name")
    if not rows:
        await update.message.reply_text("ما في مواد لسا")
        return
    lines = [f"{r['id']} — س{r['year']} ف{r['sem']} — {r['name']}" for r in rows]
    for i in range(0, len(lines), 80):
        await update.message.reply_text("\n".join(lines[i:i + 80]))


async def delsub(update: Update, ctx):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        return await update.message.reply_text("الاستخدام: /delsub رقم_المادة\n(الأرقام من /subjects)")
    sid = to_int(ctx.args[0])
    if sid is None:
        return
    x("DELETE FROM files WHERE subject_id=?", sid)
    x("DELETE FROM subjects WHERE id=?", sid)
    await update.message.reply_text("🗑 تم حذف المادة وملفاتها")


async def renamesub(update: Update, ctx):
    if not is_admin(update.effective_user.id):
        return
    if len(ctx.args) < 2:
        return await update.message.reply_text("الاستخدام: /renamesub رقم_المادة الاسم الجديد\nمثال: /renamesub 3 قواعد البيانات 1")
    x("UPDATE subjects SET name=? WHERE id=?", " ".join(ctx.args[1:])[:80], to_int(ctx.args[0]))
    await update.message.reply_text("✅ تم تعديل الاسم")


async def ban(update: Update, ctx):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        return await update.message.reply_text("الاستخدام: /ban ID")
    uid = to_int(ctx.args[0])
    if uid is None or is_admin(uid):
        return await update.message.reply_text("ما فيك تحظر هاد الحساب")
    x("INSERT OR IGNORE INTO banned(id) VALUES(?)", uid)
    await update.message.reply_text("⛔ تم الحظر")


async def unban(update: Update, ctx):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        return await update.message.reply_text("الاستخدام: /unban ID")
    x("DELETE FROM banned WHERE id=?", to_int(ctx.args[0]))
    await update.message.reply_text("✅ تم فك الحظر")


# ---------------------------- مزامنة موقع الجامعة ----------------------------
CODE_RE = re.compile(r"^[A-Z]{2,5}\d{2,4}[A-Z]?$")
CODE_FIND = re.compile(r"\b[A-Z]{2,5}\d{3}[A-Z]?\b")
FILE_FIND = re.compile(r"[^\"'<>\n\r\\]+?\.(?:pdf|pptx?|docx?|xlsx?|zip|rar)", re.I)
MAX_BYTES = 49 * 1024 * 1024      # حد تيليغرام للبوتات 50MB
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (WIU-Lectures-Bot)",
                "X-Requested-With": "XMLHttpRequest", "Referer": SITE + "/lecture/"}
_sync_lock = asyncio.Lock()


def http_client():
    return httpx.AsyncClient(timeout=60, follow_redirects=True, headers=HTTP_HEADERS)


def parse_list(text, rx):
    """يستخرج القيم من الرد سواء كان JSON أو HTML أو نص"""
    try:
        text = json.dumps(json.loads(text), ensure_ascii=False)
    except ValueError:
        pass
    out = []
    for m in rx.findall(text):
        v = unquote(m).split("/")[-1].strip(" ,;|\t")
        if v and v not in out:
            out.append(v)
    return out


async def api_get(client, name, params):
    last = "?"
    for path in (f"/lecture/{name}", f"/{name}"):
        try:
            r = await client.get(SITE + path, params=params)
            if r.status_code == 200 and r.text.strip():
                return r.text
            last = f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            last = f"{type(e).__name__}: {e}"[:200]
    raise RuntimeError(f"{name}: {last}")


async def download(client, code, fname):
    url = f"{SITE}/lectures/{FACULTY}/{code}/{quote(fname)}"
    async with client.stream("GET", url) as r:
        if r.status_code != 200:
            return None
        buf = bytearray()
        async for chunk in r.aiter_bytes():
            buf += chunk
            if len(buf) > MAX_BYTES:
                log.warning("file too big: %s", url)
                return None
        return bytes(buf)


async def sync_course(bot, client, sub):
    code = sub["code"]
    names = parse_list(await api_get(client, "getlectures.php", {"course": code}), FILE_FIND)
    first = not q("SELECT 1 FROM synced WHERE code=? LIMIT 1", code)
    new = []
    for fname in names:
        if ".." in fname or q("SELECT 1 FROM synced WHERE code=? AND fname=?", code, fname):
            continue
        title = re.sub(r"\.\w+$", "", fname)[:200]
        if not q("SELECT 1 FROM files WHERE subject_id=? AND title=?", sub["id"], title):
            data = await download(client, code, fname)
            if data is None:
                continue
            msg = await bot.send_document(STORAGE_CHAT, InputFile(data, filename=fname),
                                          caption=f"#{code}", disable_notification=True,
                                          write_timeout=180, read_timeout=60)
            x("INSERT INTO files(subject_id,cat,title,file_id,kind,added_at) VALUES(?,?,?,?,?,?)",
              sub["id"], "th", title, msg.document.file_id, "doc",
              datetime.now().isoformat(timespec="seconds"))
            new.append(title)
            await asyncio.sleep(1)
        x("INSERT OR IGNORE INTO synced(code,fname) VALUES(?,?)", code, fname)
    return new, first


async def sync_all(bot, notify=True):
    if _sync_lock.locked():
        return None
    async with _sync_lock:
        report = []
        async with http_client() as client:
            for sub in q("SELECT * FROM subjects WHERE code IS NOT NULL ORDER BY year, sem"):
                try:
                    new, first = await sync_course(bot, client, sub)
                except Exception as e:
                    log.warning("sync %s failed: %s", sub["code"], e)
                    report.append(f"⚠️ {sub['code']}: ما قدرت أوصل للموقع ({str(e)[:80]})")
                    continue
                if not new:
                    continue
                report.append(f"✅ {sub['code']} – {sub['name']}: {len(new)} ملف جديد")
                if notify and AUTO_NOTIFY and not first:   # أول سحب للمادة ما بيبعت إشعارات
                    text = f"🆕 نزلت محاضرات جديدة\n📚 {sub['name']}\n\n" + "\n".join(f"• {t}" for t in new[:10])
                    await broadcast(bot, text, M([[B("📂 افتح المحاضرات", callback_data=f"cat:{sub['id']}:th")]]))
        return report


async def sync_job(ctx):
    rep = await sync_all(ctx.bot)
    if rep:
        try:
            await ctx.bot.send_message(OWNER_ID, "🔄 مزامنة تلقائية:\n" + "\n".join(rep), disable_notification=True)
        except Exception:
            pass


async def sync_cmd(update: Update, ctx):
    if not is_admin(update.effective_user.id):
        return
    chat = update.effective_chat.id
    await update.message.reply_text("⏳ عم أسحب من موقع الجامعة... بيوصلك تقرير لما يخلص")

    async def run():
        rep = await sync_all(ctx.bot)
        if rep is None:
            txt = "في مزامنة شغالة هلق، استنى شوي"
        elif not q("SELECT 1 FROM subjects WHERE code IS NOT NULL"):
            txt = "ما في مواد مربوطة بكود. استخدم /discover أو /addcourse"
        else:
            txt = "\n".join(rep) or "✅ كلشي محدّث، ما في ملفات جديدة"
        await ctx.bot.send_message(chat, txt)
    ctx.application.create_task(run())


def guess_year(code):
    m = re.search(r"\d", code)
    y = int(m.group()) if m else 1
    return y if 1 <= y <= YEARS else 1


async def discover(update: Update, ctx):
    """يجيب أكواد المواد من الموقع برقم جامعي — الرقم ما بينخزن"""
    if not is_admin(update.effective_user.id) or not ctx.args:
        return await update.message.reply_text("الاستخدام: /discover الرقم_الجامعي")
    stud = ctx.args[0].strip()
    try:
        await update.message.delete()   # نحذف الرسالة لأنها فيها رقم جامعي
    except Exception:
        pass
    chat = update.effective_chat.id
    if not re.fullmatch(r"[A-Za-z0-9]{3,20}", stud):
        return await ctx.bot.send_message(chat, "رقم جامعي غير صالح")
    try:
        async with http_client() as client:
            text = await api_get(client, "getcourses.php", {"studId": stud, "faculty": FACULTY})
    except Exception as e:
        log.warning("discover failed: %s", e)
        return await ctx.bot.send_message(
            chat, f"⚠️ ما قدرت أوصل لموقع الجامعة\nالسبب: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
    codes = parse_list(text, CODE_FIND)
    if not codes:
        return await ctx.bot.send_message(chat, "ما لقيت مواد لهالرقم")
    known = {r["code"] for r in q("SELECT code FROM subjects WHERE code IS NOT NULL")}
    lines = ["📋 المواد يلي لقيتها (اضغط على الأمر لتنسخه وعدّل الاسم والفصل):\n"]
    for c in codes:
        if c in known:
            lines.append(f"✅ {c} (مضافة)")
        else:
            lines.append(f"🆕 {c}\n<code>/addcourse {c} {guess_year(c)} 1 اسم المادة</code>")
    await ctx.bot.send_message(chat, "\n".join(lines), parse_mode="HTML")


async def addcourse(update: Update, ctx):
    if not is_admin(update.effective_user.id):
        return
    a = ctx.args
    if len(a) < 3:
        return await update.message.reply_text(
            "الاستخدام: /addcourse الكود السنة الفصل اسم المادة\nمثال: /addcourse SE424 4 1 البرمجة التفرعية")
    code, y, s = a[0].upper(), to_int(a[1]), to_int(a[2])
    name = " ".join(a[3:]).strip()[:80] or code
    if not CODE_RE.match(code) or y is None or not 1 <= y <= YEARS or s not in (1, 2):
        return await update.message.reply_text("⚠️ في خطأ بالكود أو السنة أو الفصل")
    x("UPDATE subjects SET code=NULL WHERE code=?", code)
    x("INSERT INTO subjects(year,sem,name,code) VALUES(?,?,?,?) "
      "ON CONFLICT(year,sem,name) DO UPDATE SET code=excluded.code", y, s, name, code)
    await update.message.reply_text(f"✅ {name} ({code}) – السنة {yname(y)} {SEM_NAMES[s]}\nاكتب /sync لسحب محاضراتها")


async def delcourse(update: Update, ctx):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        return await update.message.reply_text("الاستخدام: /delcourse الكود\nمثال: /delcourse SE424")
    x("UPDATE subjects SET code=NULL WHERE code=?", ctx.args[0].upper())
    await update.message.reply_text("✅ توقفت مزامنة هالمادة (الملفات الموجودة بتضل)")


async def courses_cmd(update: Update, ctx):
    if not is_admin(update.effective_user.id):
        return
    rows = q("SELECT * FROM subjects WHERE code IS NOT NULL ORDER BY year, sem, name")
    if not rows:
        return await update.message.reply_text("ما في مواد مربوطة بالموقع لسا")
    await update.message.reply_text("\n".join(
        f"{r['code']} — س{r['year']} ف{r['sem']} — {r['name']}" for r in rows))


async def cancel(update: Update, ctx):
    ctx.user_data.pop("queue", None)
    ctx.user_data.pop("awaiting", None)
    await update.message.reply_text("تم الإلغاء ✅", reply_markup=main_menu())


# ---------------------------- استقبال الملفات (مشرفين) ----------------------------
async def on_file(update: Update, ctx):
    m = update.message
    if not is_admin(update.effective_user.id):
        await m.reply_text("📤 رفع الملفات للمشرفين فقط.\nإذا عندك محاضرة مو موجودة، ابعتها لأحد المشرفين 🙏")
        return
    if m.document:
        fid, kind, name = m.document.file_id, "doc", m.document.file_name or "ملف"
        if not name.lower().endswith(ALLOWED_EXT):
            await m.reply_text("⚠️ نوع الملف غير مسموح (المسموح: PDF, Word, PowerPoint, Excel, ZIP)")
            return
    elif m.photo:
        fid, kind, name = m.photo[-1].file_id, "photo", "صورة"
    elif m.video:
        fid, kind, name = m.video.file_id, "video", m.video.file_name or "فيديو"
    else:
        return
    title = (m.caption or name or "ملف").strip()[:200]
    title = re.sub(r"\.(pdf|docx?|pptx?)$", "", title, flags=re.I)

    # توجيه تلقائي: اسم الملف بيبلش بكود مادة مربوطة، مثل "SE424 - Lecture01 ..."
    mc = re.match(r"^([A-Z]{2,5}\d{2,4}[A-Z]?)\s*-\s*(.+)$", title)
    if mc:
        sub = q("SELECT * FROM subjects WHERE code=?", mc.group(1))
        if sub:
            return await auto_file(update, ctx, sub[0], fid, kind, mc.group(2).strip())
    queue = ctx.user_data.setdefault("queue", [])
    queue.append((fid, kind, title))
    if len(queue) == 1:  # أول ملف بالدفعة → نسأل عن المكان مرة وحدة
        await m.reply_text("📥 وين بدك تحفظ الملف؟\n(فيك تبعت كذا ملف ورا بعض وكلهن بينحفظوا بنفس المكان)",
                           reply_markup=upload_menu(ctx))


async def auto_file(update, ctx, sub, fid, kind, title):
    st = ctx.user_data.setdefault("auto", {})        # sid -> [محفوظ, مكرر, اسم]
    rec = st.setdefault(sub["id"], [0, 0, sub["name"]])
    if q("SELECT 1 FROM files WHERE subject_id=? AND title=?", sub["id"], title):
        rec[1] += 1
    else:
        x("INSERT INTO files(subject_id,cat,title,file_id,kind,added_at) VALUES(?,?,?,?,?,?)",
          sub["id"], "th", title, fid, kind, datetime.now().isoformat(timespec="seconds"))
        rec[0] += 1
    # تقرير واحد بعد ما توقف الملفات عن الوصول (بدل رد على كل ملف)
    uid = update.effective_user.id
    name = f"auto{uid}"
    for j in ctx.job_queue.get_jobs_by_name(name):
        j.schedule_removal()
    ctx.job_queue.run_once(auto_summary, 4, chat_id=update.effective_chat.id, user_id=uid, name=name)


async def auto_summary(ctx):
    st = ctx.user_data.pop("auto", {})
    if not st:
        return
    lines, btns = ["📥 <b>ترتيب تلقائي</b>\n"], []
    for sid, (saved, skipped, name) in st.items():
        line = f"📚 {html.escape(name)}: ✅ {saved} جديد"
        if skipped:
            line += f" | ⏭ {skipped} موجود مسبقاً"
        lines.append(line)
        if saved:
            btns.append([B(f"🔔 أبلغ الطلاب – {name}"[:60], callback_data=f"notify:{sid}:th")])
    await ctx.bot.send_message(ctx.job.chat_id, "\n".join(lines), parse_mode="HTML",
                               reply_markup=M(btns) if btns else None)


# ---------------------------- النصوص: إنشاء مادة / بحث ----------------------------
async def on_text(update: Update, ctx):
    uid = update.effective_user.id
    if is_banned(uid) or not rate_ok(uid):
        return
    text = update.message.text.strip()[:100]
    aw = ctx.user_data.get("awaiting")
    if aw and is_admin(uid) and aw[0] == "newsub":
        _, y, s = aw
        ctx.user_data.pop("awaiting")
        text = text[:80]
        x("INSERT OR IGNORE INTO subjects(year,sem,name) VALUES(?,?,?)", y, s, text)
        sid = q("SELECT id FROM subjects WHERE year=? AND sem=? AND name=?", y, s, text)[0]["id"]
        await update.message.reply_text(f"✅ المادة: {text}\nاختار نوع الملف:",
                                        reply_markup=cats_kb(sid, "ucat", "ucancel"))
        return

    # بحث
    if len(text) < 2:
        return await update.message.reply_text("اكتب حرفين على الأقل للبحث 🔍")
    key = "%" + norm(text).replace("%", "").replace("_", "") + "%"
    subs = q("SELECT * FROM subjects WHERE norm(name) LIKE ? ORDER BY year, sem LIMIT 20", key)
    fls = q("SELECT f.id, f.title, s.name FROM files f JOIN subjects s ON s.id=f.subject_id "
            "WHERE norm(f.title) LIKE ? LIMIT 15", key)
    if not subs and not fls:
        await update.message.reply_text("ما لقيت شي 😕 جرّب كلمة تانية أو تصفح من القائمة",
                                        reply_markup=main_menu())
        return
    rows = [[B(f"📚 {r['name']} (س{r['year']} ف{r['sem']})", callback_data=f"sub:{r['id']}")] for r in subs]
    rows += [[B(f"📎 {r['title'][:40]} – {r['name'][:15]}", callback_data=f"f:{r['id']}")] for r in fls]
    rows.append([B("🏠 الرئيسية", callback_data="home")])
    await update.message.reply_text(f"🔍 نتائج البحث عن «{text}»:", reply_markup=M(rows))


# ---------------------------- الأزرار ----------------------------
async def on_cb(update: Update, ctx):
    qy = update.callback_query
    if is_banned(qy.from_user.id):
        return await qy.answer()
    if not rate_ok(qy.from_user.id):
        return await qy.answer("⏳ على مهلك شوي، جرّب بعد ثواني", show_alert=True)
    try:
        await handle_cb(update, ctx)
    except (ValueError, IndexError, KeyError, TypeError):
        await qy.answer("طلب غير صالح")  # بيانات مزورة أو قديمة


async def handle_cb(update: Update, ctx):
    qy = update.callback_query
    d = (qy.data or "").split(":")
    a = d[0]
    uid = qy.from_user.id
    adm = is_admin(uid)
    chat = qy.message.chat_id
    await qy.answer()

    # ----- تصفح الطلاب -----
    if a == "home":
        await safe_edit(qy, "اختار السنة الدراسية 👇", main_menu())

    elif a == "y":
        y = int(d[1])
        await safe_edit(qy, f"🎓 السنة {yname(y)} – اختار الفصل:", M([
            [B("الفصل الثاني", callback_data=f"s:{y}:2"), B("الفصل الأول", callback_data=f"s:{y}:1")],
            [B("🔙 رجوع", callback_data="home")]]))

    elif a == "s":
        y, s = int(d[1]), int(d[2])
        subs = q("SELECT * FROM subjects WHERE year=? AND sem=? ORDER BY name", y, s)
        rows = [[B(f"📚 {r['name']}", callback_data=f"sub:{r['id']}")] for r in subs]
        rows.append([B("🔙 رجوع", callback_data=f"y:{y}")])
        txt = f"السنة {yname(y)} – {SEM_NAMES[s]}\n" + ("اختار المادة:" if subs else "ما في مواد مضافة لسا ⏳")
        await safe_edit(qy, txt, M(rows))

    elif a == "sub":
        s = subj(int(d[1]))
        if not s:
            return await safe_edit(qy, "المادة محذوفة", main_menu())
        await safe_edit(qy, f"📚 {s['name']}\nاختار النوع:",
                        cats_kb(s["id"], "cat", f"s:{s['year']}:{s['sem']}"))

    elif a == "cat":
        sid, cat = int(d[1]), d[2]
        fls = q("SELECT id, title FROM files WHERE subject_id=? AND cat=? ORDER BY id", sid, cat)
        rows = [[B(f"📎 {r['title'][:55]}", callback_data=f"f:{r['id']}")] for r in fls]
        if len(fls) > 1:
            rows.insert(0, [B(f"📦 إرسال الكل ({len(fls)})", callback_data=f"all:{sid}:{cat}")])
        rows.append([B("🔙 رجوع", callback_data=f"sub:{sid}")])
        await safe_edit(qy, place_name(sid, cat) + ("" if fls else "\n\nما في ملفات لسا ⏳"), M(rows))

    elif a == "f":
        r = q("SELECT * FROM files WHERE id=?", int(d[1]))
        if r:
            await send_file(ctx.bot, chat, r[0], adm)

    elif a == "all":
        if not bulk_ok(uid):
            return await ctx.bot.send_message(chat, "⏳ استنى 30 ثانية قبل ما تطلب «إرسال الكل» مرة تانية")
        for r in q("SELECT * FROM files WHERE subject_id=? AND cat=? ORDER BY id", int(d[1]), d[2]):
            await send_file(ctx.bot, chat, r, adm)
            await asyncio.sleep(0.1)

    elif a == "sched":
        fls = q("SELECT * FROM files WHERE cat='sched' ORDER BY id DESC")
        if not fls:
            await ctx.bot.send_message(chat, "📅 البرنامج الامتحاني ما نزل لسا")
        for r in fls:
            await send_file(ctx.bot, chat, r, adm)

    elif a == "searchhelp":
        await ctx.bot.send_message(chat, "🔍 اكتب اسم المادة أو جزء منه (مثلاً: شبكات، خوارزميات)")

    # ----- المشرفين -----
    elif not adm:
        return

    elif a == "del":
        x("DELETE FROM files WHERE id=?", int(d[1]))
        try:
            await qy.edit_message_caption("🗑 تم حذف هذا الملف من البوت")
        except BadRequest:
            pass

    elif a == "ucancel":
        ctx.user_data.pop("queue", None)
        ctx.user_data.pop("awaiting", None)
        await safe_edit(qy, "❌ تم الإلغاء")

    elif a == "uy":
        y = int(d[1])
        await safe_edit(qy, f"السنة {yname(y)} – الفصل؟", M([
            [B("الفصل الثاني", callback_data=f"us:{y}:2"), B("الفصل الأول", callback_data=f"us:{y}:1")],
            [B("❌ إلغاء", callback_data="ucancel")]]))

    elif a == "us":
        y, s = int(d[1]), int(d[2])
        subs = q("SELECT * FROM subjects WHERE year=? AND sem=? ORDER BY name", y, s)
        rows = [[B(r["name"], callback_data=f"usub:{r['id']}")] for r in subs]
        rows.append([B("➕ مادة جديدة", callback_data=f"unew:{y}:{s}")])
        rows.append([B("❌ إلغاء", callback_data="ucancel")])
        await safe_edit(qy, "اختار المادة:", M(rows))

    elif a == "unew":
        ctx.user_data["awaiting"] = ("newsub", int(d[1]), int(d[2]))
        await safe_edit(qy, "✍️ اكتب اسم المادة الجديدة:")

    elif a == "usub":
        sid = int(d[1])
        await safe_edit(qy, f"📚 {subj(sid)['name']}\nنوع الملف؟", cats_kb(sid, "ucat", "ucancel"))

    elif a in ("ucat", "usched", "ulast"):
        if a == "ucat":
            sid, cat = int(d[1]), d[2]
        elif a == "usched":
            sid, cat = 0, "sched"
        else:
            sid, cat = ctx.user_data["last"]
        if cat not in CATS and cat != "sched":
            return
        n = save_queue(ctx, sid, cat)
        await safe_edit(qy, f"✅ تم حفظ {n} ملف في:\n{place_name(sid, cat)}", saved_kb(sid, cat))

    elif a == "notify":
        sid, cat = int(d[1]), d[2]
        await safe_edit(qy, "⏳ عم يتم إبلاغ الطلاب...")
        btn = M([[B("📂 افتح", callback_data="sched" if cat == "sched" else f"cat:{sid}:{cat}")]])
        ok, fail = await broadcast(ctx.bot, f"🆕 نزل ملف جديد:\n{place_name(sid, cat)}", btn)
        await ctx.bot.send_message(chat, f"📢 وصل الإشعار لـ {ok} طالب")


async def on_error(update, ctx):
    log.exception("Error", exc_info=ctx.error)


async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start", "🏠 القائمة الرئيسية"),
        BotCommand("cancel", "❌ إلغاء العملية"),
    ])
    await app.bot.set_my_description(
        "📚 بوت محاضرات الهندسة المعلوماتية – جامعة الوادي الخاصة\n"
        "محاضرات نظري وعملي، أسئلة دورات، ملخصات، والبرنامج الامتحاني 🎓")
    await app.bot.set_my_short_description("محاضرات المعلوماتية – جامعة الوادي 📚")


def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    pv = filters.ChatType.PRIVATE  # البوت بيشتغل بالخاص بس
    app.add_handler(CommandHandler("start", start, filters=pv))
    app.add_handler(CommandHandler("admin", admin_cmd, filters=pv))
    app.add_handler(CommandHandler("addadmin", addadmin, filters=pv))
    app.add_handler(CommandHandler("deladmin", deladmin, filters=pv))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd, filters=pv))
    app.add_handler(CommandHandler("subjects", subjects_cmd, filters=pv))
    app.add_handler(CommandHandler("delsub", delsub, filters=pv))
    app.add_handler(CommandHandler("renamesub", renamesub, filters=pv))
    app.add_handler(CommandHandler("ban", ban, filters=pv))
    app.add_handler(CommandHandler("unban", unban, filters=pv))
    app.add_handler(CommandHandler("sync", sync_cmd, filters=pv))
    app.add_handler(CommandHandler("discover", discover, filters=pv))
    app.add_handler(CommandHandler("addcourse", addcourse, filters=pv))
    app.add_handler(CommandHandler("delcourse", delcourse, filters=pv))
    app.add_handler(CommandHandler("courses", courses_cmd, filters=pv))
    app.add_handler(CommandHandler("cancel", cancel, filters=pv))
    app.add_handler(MessageHandler(pv & (filters.Document.ALL | filters.PHOTO | filters.VIDEO), on_file))
    app.add_handler(MessageHandler(pv & filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_error_handler(on_error)
    if SYNC_MIN > 0:
        app.job_queue.run_repeating(sync_job, interval=SYNC_MIN * 60, first=120)
    log.info("Bot started")
    app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=True)


if __name__ == "__main__":
    main()
