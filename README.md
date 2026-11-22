<p align="center">
  <img src="assets/bot.png" width="140" alt="Muhadarati">
</p>

<h1 align="center">Muhadarati Bot</h1>

<p align="center">English · <a href="README.ar.md">العربية</a></p>

<p align="center">
  A Telegram bot that gives Informatics Engineering students at Al-Wadi Private University<br>
  their lectures, past exam papers, summaries and exam schedule in a few taps.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white">
  <img src="https://img.shields.io/badge/python--telegram--bot-22.x-26A5E4?logo=telegram&logoColor=white">
  <img src="https://img.shields.io/badge/DB-SQLite-003B57?logo=sqlite&logoColor=white">
</p>

---

## Why it exists

Lecture files were scattered across the university website and WhatsApp groups. Muhadarati puts them in one organised place inside Telegram, notifies students when something new is added, and lets a small team of admins keep it up to date in seconds.

## Features

**For students**
- Organised browsing: year → semester → course → theory / lab / past exams / summaries
- Search by course or lecture name, tolerant of Arabic spelling variants (ة/ه, أ/ا, diacritics)
- "Send all" button to download every file in a section at once
- Instant notification when a new lecture is published

**For admins**
- Upload by forwarding files from WhatsApp or anywhere else, one file or a whole batch
- Automatic filing of any file whose name starts with a course code (e.g. `SE424 - Lecture01.pdf`)
- Duplicate detection and a "same place" shortcut for fast uploads
- Broadcast messages, user bans and admin management
- A browser bookmarklet that collects new lectures from the university website

## Security
- Every SQL query is parameterised (no SQL injection)
- Role hierarchy: owner → admins → students
- Works in private chats only
- Rate limiting against spam; forged callback buttons are rejected without crashing the bot
- File-type allow-list; the bot token never appears in logs
- On the server: a dedicated non-root user, a sandboxed systemd service and a `.env` file with 600 permissions
- Stores only Telegram `file_id`s, not the files themselves, and no student ID numbers

## Tech stack
Python 3.10+, python-telegram-bot 22, SQLite, systemd on Ubuntu, vanilla JavaScript (bookmarklet).

## Project structure
```
muhadarati-bot/
├── bot.py               # the bot
├── requirements.txt
├── .env.example         # settings template (copy to .env)
├── .gitignore
├── deploy/
│   ├── install.sh       # one-command server install
│   └── lecbot.service   # systemd service
├── tools/
│   ├── bookmarklet.js   # browser button source (readable)
│   ├── bookmarklet.txt  # same code on one line, to paste as a bookmark
│   └── diag.py          # connection check for the university website
└── assets/              # bot and channel images (PNG + SVG)
```

## Run locally (Windows)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env     # then fill in BOT_TOKEN and OWNER_ID
python bot.py
```

## Configuration (`.env`)
| Variable | Description |
|---|---|
| `BOT_TOKEN` | Bot token from @BotFather |
| `OWNER_ID` | Your Telegram user ID (bot owner) |
| `YEARS` | Number of study years (default 5) |
| `DB_PATH` | Database file path |
| `STORAGE_CHAT_ID` | Private channel ID used to store files (starts with -100) |
| `FACULTY_ID` | Faculty number on the university website |
| `SYNC_MINUTES` | Server-side sync interval, `0` = off (recommended) |
| `AUTO_NOTIFY` | Notify students automatically after a sync |

## Deploy to a server (Ubuntu)
```bash
git clone https://github.com/alibarakat-dev/muhadarati-bot.git
cd muhadarati-bot
cp .env.example .env && nano .env
sudo bash deploy/install.sh
```
Daily backup (`sudo crontab -e`):
```
0 4 * * * sqlite3 /opt/lecbot/bot.db ".backup /root/lecbot-$(date +\%F).db"
```

## Admin commands
| Command | Purpose |
|---|---|
| `/admin` | Admin panel and statistics |
| `/subjects` `/renamesub` `/delsub` | Manage courses |
| `/addcourse` `/courses` `/delcourse` | Link courses to website codes |
| `/discover` `/sync` | Sync tools (off by default) |
| `/broadcast` | Message all students |
| `/ban` `/unban` | Ban / unban a user |
| `/addadmin` `/deladmin` | Manage admins (owner only) |
| `/cancel` | Cancel the current action |

Send any command without arguments to see how to use it.

## Author
Built by **Ali Barakat** · [Portfolio](https://alibarakat-dev.github.io) · [GitHub](https://github.com/alibarakat-dev)
