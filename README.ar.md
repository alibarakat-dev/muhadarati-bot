<p align="center">
  <img src="assets/bot.png" width="140" alt="Muhadarati">
</p>

<h1 align="center">محاضراتي – Muhadarati Bot</h1>

<p align="center"><a href="README.md">English</a> · العربية</p>

<p align="center">
  بوت تيليغرام لطلاب الهندسة المعلوماتية في جامعة الوادي الخاصة<br>
  محاضرات نظري وعملي • أسئلة دورات • ملخصات • البرنامج الامتحاني
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white">
  <img src="https://img.shields.io/badge/python--telegram--bot-22.x-26A5E4?logo=telegram&logoColor=white">
  <img src="https://img.shields.io/badge/DB-SQLite-003B57?logo=sqlite&logoColor=white">
</p>

---

## ✨ المميزات

**للطلاب**
- تصفح مرتب: السنة ← الفصل ← المادة ← (نظري / عملي / أسئلة دورات / ملخصات)
- بحث باسم المادة أو المحاضرة، بيتحمّل اختلاف الكتابة (ة/ه، أ/ا، التشكيل)
- زر «إرسال الكل» لتنزيل كل ملفات القسم دفعة وحدة
- إشعار فوري لما تنزل محاضرة جديدة

**للمشرفين**
- رفع بالتحويل (Forward) من واتساب أو أي مكان، وكذا ملف دفعة وحدة
- ترتيب تلقائي لأي ملف اسمه بيبلش بكود مادة (مثل `SE424 - Lecture01.pdf`)
- منع تكرار الملفات، وزر «📌 نفس المكان» لتسريع الرفع
- رسائل جماعية، حظر، وإدارة مشرفين
- زر بالمتصفح (Bookmarklet) لجلب المحاضرات الجديدة من موقع الجامعة

## 🔒 الحماية
- كل استعلامات SQL مُمرّرة كبارامترات (لا SQL Injection)
- صلاحيات متدرجة: مالك ← مشرفين ← طلاب
- البوت بيشتغل بالمحادثات الخاصة بس
- حد للطلبات ضد السبام، ورفض أي أزرار مزوّرة بدون ما يوقع البوت
- قائمة بيضاء لأنواع الملفات، والتوكن ما بيظهر باللوغ
- على السيرفر: مستخدم منفصل مو root، و systemd sandbox، و `.env` بصلاحية 600
- البوت ما بيخزن ملفات، بس `file_id` تبع تيليغرام، وما بيخزن أرقام جامعية

## 📁 هيكل المشروع
```
muhadarati-bot/
├── bot.py               # البوت كامل
├── requirements.txt
├── .env.example         # نموذج الإعدادات (انسخه لـ .env)
├── .gitignore
├── deploy/
│   ├── install.sh       # تنصيب على السيرفر بأمر واحد
│   └── lecbot.service   # خدمة systemd
├── tools/
│   ├── bookmarklet.js   # كود زر المتصفح (مقروء)
│   ├── bookmarklet.txt  # نفس الكود بسطر واحد للصق بالمفضلة
│   └── diag.py          # فحص الاتصال بموقع الجامعة
└── assets/              # صور البوت والقناة (PNG + SVG)
```

## 🚀 التشغيل المحلي (ويندوز)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env     # وعبّي BOT_TOKEN و OWNER_ID
python bot.py
```

## ⚙️ الإعدادات (`.env`)
| المتغير | الشرح |
|---|---|
| `BOT_TOKEN` | توكن البوت من @BotFather |
| `OWNER_ID` | الـ ID تبعك (مالك البوت) |
| `YEARS` | عدد السنوات الدراسية (افتراضي 5) |
| `DB_PATH` | مسار قاعدة البيانات |
| `STORAGE_CHAT_ID` | ID قناة خاصة لتخزين الملفات (بيبلش بـ -100) |
| `FACULTY_ID` | رقم الكلية بموقع الجامعة (4 = معلوماتية) |
| `SYNC_MINUTES` | المزامنة من السيرفر، `0` = طافية (اتركها 0) |
| `AUTO_NOTIFY` | إشعار الطلاب تلقائياً بعد المزامنة |

## 🖥️ النشر على السيرفر (Ubuntu)
```bash
git clone https://github.com/alibarakat-dev/muhadarati-bot.git
cd muhadarati-bot
cp .env.example .env && nano .env
sudo bash deploy/install.sh
```
نسخة احتياطية يومية (`sudo crontab -e`):
```
0 4 * * * sqlite3 /opt/lecbot/bot.db ".backup /root/lecbot-$(date +\%F).db"
```

## 📥 جلب المحاضرات من موقع الجامعة
موقع الجامعة بيحظر الطلبات الآلية، فالجلب بيصير من متصفحك وبكبسة منك:
1. بـ Chrome: كليك يمين على شريط المفضلة ← Add page ← الصق محتوى `tools/bookmarklet.txt` بخانة الرابط.
2. بالبوت اربط المواد: `/addcourse SE424 4 1 البرمجة التفرعية`
3. افتح صفحة المحاضرات بالموقع، اكبس الزر، بتنزل الملفات الجديدة بس باسم `SE424 - ...pdf`
4. اسحب الملفات للبوت بتيليغرام ديسكتوب، بيرتبها لحالو وبيعطيك زر «🔔 أبلغ الطلاب».

> المزامنة من السيرفر موجودة بالكود بس طافية. لا تشغّلها إلا بموافقة الجامعة، وإلا بيتحظر عنوان السيرفر.

## 🛠️ أوامر المشرف
| الأمر | الوظيفة |
|---|---|
| `/admin` | لوحة المشرف والإحصائيات |
| `/subjects` `/renamesub` `/delsub` | إدارة المواد |
| `/addcourse` `/courses` `/delcourse` | ربط المواد بأكواد الموقع |
| `/discover` `/sync` | أدوات المزامنة (طافية افتراضياً) |
| `/broadcast` | رسالة لكل الطلاب |
| `/ban` `/unban` | حظر / فك حظر |
| `/addadmin` `/deladmin` | إدارة المشرفين (للمالك فقط) |
| `/cancel` | إلغاء أي عملية |

أي أمر بتبعتو بدون تفاصيل بيشرح طريقة استخدامه.

## ⚠️ قبل الرفع على GitHub
- ملف `.env` و `bot.db` ممنوعين من الرفع عبر `.gitignore`، لا تشيلهم منه.
- إذا انرفع التوكن بالغلط: فوراً `/revoke` من @BotFather.
