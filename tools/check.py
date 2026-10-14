#!/usr/bin/env python3
"""Pre-publish and post-publish checks for blog.nmedia.pro.

  python3 tools/check.py pre  [dist_dir]      -> checks built site before upload
  python3 tools/check.py post [slug ...]      -> checks live site after upload
Exit code 1 if any ERROR.
"""
import json, os, re, sys, subprocess, html
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = "https://blog.nmedia.pro"
errors, warns = [], []


def err(m): errors.append(m)
def warn(m): warns.append(m)


def words(t):
    return set(w for w in re.findall(r"[а-яёa-z0-9]+", t.lower()) if len(w) > 3)


def pre(dist):
    pages = [d for d in os.listdir(dist) if os.path.isfile(os.path.join(dist, d, "index.html"))]
    titles = {}
    for slug in pages:
        p = os.path.join(dist, slug, "index.html")
        h = open(p, encoding="utf-8").read()
        t = re.search(r"<title>(.*?)</title>", h, re.S)
        t = html.unescape(t.group(1)) if t else ""
        d = re.search(r'<meta name="description" content="(.*?)"', h)
        d = html.unescape(d.group(1)) if d else ""
        if not (30 <= len(t) <= 90): warn(f"{slug}: title {len(t)} симв. (норма 30–90)")
        if not (100 <= len(d) <= 180): warn(f"{slug}: description {len(d)} симв. (норма 100–180)")
        if h.count("<h1") != 1: err(f"{slug}: должен быть ровно один h1")
        if f'<link rel="canonical" href="{SITE}/{slug}/">' not in h: err(f"{slug}: canonical неверный")
        for ld in re.findall(r'<script type="application/ld\+json">(.*?)</script>', h, re.S):
            try: json.loads(ld)
            except Exception as e: err(f"{slug}: битый JSON-LD {e}")
        if "FAQPage" not in h: warn(f"{slug}: нет блока FAQ")
        if 'class="tldr"' not in h: err(f"{slug}: нет блока «Коротко» (short в front matter)")
        if "{{" in h: err(f"{slug}: остался необработанный шорткод {{...}}")
        if h.count("nmedia.pro/academy") < 3: err(f"{slug}: мало ссылок на курс")
        for href in re.findall(r'href="([^"]+)"', h):
            if "nmedia.pro/academy" in href and "utm_source=blog" not in href: err(f"{slug}: ссылка на курс без UTM")
            if href.startswith("/") and not href.startswith("//"):
                path = href.split("#")[0].split("?")[0]
                f = os.path.join(dist, path.lstrip("/"))
                if path and not (os.path.isfile(f) or os.path.isfile(os.path.join(f, "index.html"))):
                    err(f"{slug}: битая внутренняя ссылка {href}")
        for src in re.findall(r'<img[^>]+src="([^"]+)"', h):
            if src.startswith("/") and not os.path.isfile(os.path.join(dist, src.lstrip("/"))):
                err(f"{slug}: нет картинки {src}")
        if not os.path.isfile(os.path.join(dist, slug, "cover.png")): err(f"{slug}: нет обложки")
        text = re.sub(r"<[^>]+>", " ", re.search(r'<article class="body">(.*)</article>', h, re.S).group(1))
        nwords = len(re.findall(r"\w+", text))
        if nwords < 900: warn(f"{slug}: короткая статья ({nwords} слов)")
        titles[slug] = words(re.split(r"[:—]", t)[0])
    # cannibalisation: overlapping titles
    sl = list(titles)
    for i in range(len(sl)):
        for j in range(i + 1, len(sl)):
            a, b = titles[sl[i]], titles[sl[j]]
            if a and b and len(a & b) / min(len(a), len(b)) >= 0.7:
                err(f"возможная каннибализация: {sl[i]} ↔ {sl[j]} (заголовки почти совпадают)")
    sm = open(os.path.join(dist, "sitemap.xml"), encoding="utf-8").read()
    for slug in pages:
        if f"{SITE}/{slug}/" not in sm: err(f"{slug}: нет в sitemap.xml")
    mobile_check(dist, pages)
    return pages


def mobile_check(dist, pages):
    from playwright.sync_api import sync_playwright
    import http.server, threading, functools

    class Q(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Q, directory=dist))
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 360, "height": 800})
        for slug in [""] + pages:
            pg.goto(f"http://127.0.0.1:{port}/{slug + '/' if slug else ''}")
            pg.wait_for_timeout(250)
            sw = pg.evaluate("document.documentElement.scrollWidth")
            if sw > 361: err(f"{slug or 'главная'}: горизонтальная прокрутка на телефоне ({sw}px)")
        b.close()
    srv.shutdown()


def post(slugs):
    def get(u):
        r = subprocess.run(["curl", "-s", "-m", "25", "-o", "/tmp/_chk", "-w", "%{http_code}", u], capture_output=True, text=True)
        return r.stdout, (open("/tmp/_chk", encoding="utf-8", errors="ignore").read() if os.path.exists("/tmp/_chk") else "")
    for u in ["/", "/sitemap.xml", "/robots.txt", "/feed.xml"] + [f"/{s}/" for s in slugs]:
        code, body = "000", ""
        for _ in range(3):
            code, body = get(SITE + u)
            if code == "200": break
        if code != "200": err(f"LIVE {u}: HTTP {code}")
    code, sm = get(SITE + "/sitemap.xml")
    for s in slugs:
        if f"/{s}/" not in sm: err(f"LIVE {s}: нет в живом sitemap")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre"
    if mode == "pre":
        pages = pre(sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "dist"))
        print(f"проверено страниц: {len(pages)}")
    else:
        post(sys.argv[2:])
    for w in warns: print("WARN ", w)
    for e in errors: print("ERROR", e)
    print("OK" if not errors else f"ОШИБОК: {len(errors)}")
    sys.exit(1 if errors else 0)
