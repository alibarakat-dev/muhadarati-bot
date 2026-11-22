# -*- coding: utf-8 -*-
"""فحص الاتصال بموقع الجامعة — شغّلو بـ:  python diag.py"""
import httpx

SITE = "https://wiu.edu.sy"
API = SITE + "/lecture/getlectures.php"
PARAMS = {"course": "SE424"}

CHROME = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"),
    "Accept": "*/*",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
    "Referer": SITE + "/lecture/",
    "X-Requested-With": "XMLHttpRequest",
}


def show(name, fn):
    try:
        r = fn()
        print(f"[{name}] ✅ {r.status_code} -> {r.text[:120]!r}")
    except Exception as e:
        print(f"[{name}] ❌ {type(e).__name__}: {e}")


print("1) طلب عادي")
show("plain", lambda: httpx.get(API, params=PARAMS, timeout=30))

print("2) بهوية متصفح Chrome")
show("chrome", lambda: httpx.get(API, params=PARAMS, headers=CHROME, timeout=30))

print("3) متصفح + زيارة الصفحة أولاً (كوكيز)")
def with_cookies():
    with httpx.Client(headers=CHROME, timeout=30, follow_redirects=True) as c:
        c.get(SITE + "/lecture/")
        return c.get(API, params=PARAMS)
show("cookies", with_cookies)

print("4) HTTP بدل HTTPS")
show("http", lambda: httpx.get(API.replace("https", "http"), params=PARAMS, headers=CHROME, timeout=30))

print("5) تحميل ملف PDF")
pdf = SITE + "/lectures/4/SE424/Lecture01%20Introduction%20to%20Parallel%20Processing.pdf"
show("pdf", lambda: httpx.get(pdf, headers=CHROME, timeout=60))
