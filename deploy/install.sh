#!/usr/bin/env bash
# تنصيب البوت على سيرفر لينكس (Ubuntu/Debian) — شغّله من مجلد المشروع بـ: sudo bash deploy/install.sh
set -euo pipefail
[ -f .env ] || { echo "❌ لازم تعمل ملف .env أولاً (انسخ .env.example وعبّيه)"; exit 1; }
id lecbot &>/dev/null || useradd -r -s /usr/sbin/nologin lecbot
mkdir -p /opt/lecbot
cp bot.py requirements.txt .env /opt/lecbot/
cd /opt/lecbot
[ -d venv ] || python3 -m venv venv
venv/bin/pip install -q -r requirements.txt
chown -R lecbot:lecbot /opt/lecbot
chmod 600 /opt/lecbot/.env
cp "$OLDPWD/deploy/lecbot.service" /etc/systemd/system/lecbot.service
systemctl daemon-reload
systemctl enable --now lecbot
systemctl restart lecbot
echo "✅ البوت شغّال. للمتابعة: journalctl -u lecbot -f"
