#!/usr/bin/env python3
"""Static blog generator for blog.nmedia.pro.

content/articles/<slug>.md  ->  dist/<slug>/index.html
Front matter (between --- lines), simple `key: value`:
  title, description, h1, date (YYYY-MM-DD), updated, category, keywords,
  cover_kicker, cover_title, status (draft|published), lead
Placeholders in markdown body: {{cta_course}}, {{cta_tg}}
"""
import html, json, os, re, shutil, subprocess, sys, datetime, urllib.parse

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = "https://blog.nmedia.pro"
COURSE = "https://nmedia.pro/academy"
STUDIO = "https://nmedia.pro/"
TG = "https://t.me/neuromedia_tg"
PROMO = "Блог"
AUTHOR = "Никита Седов"
AUTHOR_ROLE = "основатель AI-студии НЕЙРОМЕДИА"
BRAND = "НЕЙРОМЕДИА"
METRIKA_ID = os.environ.get("METRIKA_ID", "112138775")
def _find_marked():
    cands = [os.environ.get("MARKED", ""), "/home/claude/.npm-global/lib/node_modules/marked/lib/marked.esm.js"]
    try:
        root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
        cands.append(os.path.join(root, "marked/lib/marked.esm.js"))
    except Exception:
        pass
    cands.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "node_modules/marked/lib/marked.esm.js"))
    for c in cands:
        if c and os.path.isfile(c):
            return c
    raise SystemExit("marked не найден: npm install -g marked (или npm install marked в папке блога)")


MARKED = _find_marked()
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]

CATEGORIES = {
    "obuchenie": "Обучение",
    "instrumenty": "Инструменты",
    "dlya-biznesa": "ИИ-видео для бизнеса",
    "zarabotok": "Заработок",
}


def utm(url, slug, content):
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}utm_source=blog&utm_medium=article&utm_campaign={slug}&utm_content={content}"


def md_to_html(md):
    js = ("import {marked} from '%s';let s='';process.stdin.on('data',d=>s+=d)"
          ".on('end',()=>process.stdout.write(marked.parse(s,{gfm:true})))" % MARKED)
    r = subprocess.run(["node", "--input-type=module", "-e", js], input=md.encode(), capture_output=True, check=True)
    return r.stdout.decode()


def parse(path):
    raw = open(path, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    meta, body = {}, raw
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = m.group(2)
    meta["slug"] = os.path.splitext(os.path.basename(path))[0]
    meta["md"] = body
    return meta


def inline_md(t):
    t = html.escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', t)
    return t


def ru_date(s):
    d = datetime.date.fromisoformat(s)
    return f"{d.day} {MONTHS[d.month-1]} {d.year}"


def slugify_ru(text):
    tr = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                  ["a","b","v","g","d","e","e","zh","z","i","y","k","l","m","n","o","p","r","s","t","u","f","h","ts","ch","sh","sch","","y","","e","yu","ya"]))
    t = "".join(tr.get(c, c) for c in text.lower())
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:60]


MEDIA = {m["id"]: m for m in json.load(open(os.path.join(ROOT, "static/media/library.json"), encoding="utf-8"))}


def frame_html(m):
    item = MEDIA[m.group(1)]
    cap = (m.group(2) or "").strip() or "Кадр из работ AI-студии НЕЙРОМЕДИА"
    return (f'<figure class="frame"><img src="{item["src"]}" loading="lazy" decoding="async" width="1600" height="900" '
            f'alt="{html.escape(item["alt"])}"><figcaption>{html.escape(cap)}</figcaption></figure>')


DEFAULT_CTA_TITLE = "Хотите делать такие ролики сами?"
DEFAULT_CTA_TEXT = "В курсе НЕЙРОМЕДИА проходим весь путь, как на заказе студии: сценарий, кадры, анимация, звук и монтаж."


def cta_inline(slug, n, meta=None):
    meta = meta or {}
    title = meta.get("cta_title") or DEFAULT_CTA_TITLE
    text = meta.get("cta_text") or DEFAULT_CTA_TEXT
    return (f'<div class="cta-inline"><div class="t"><b>{html.escape(title)}</b>'
            f'<span>{html.escape(text)}</span></div>'
            f'<a class="btn" href="{html.escape(utm(COURSE, slug, f"inline{n}"))}">Смотреть программу →</a></div>')


VIDEOS = {
    "vozm1": "Фрагмент из работ студии", "vozm2": "Фрагмент из работ студии",
    "vozm3": "Фрагмент из работ студии", "vozm4": "Фрагмент из работ студии",
}


_DIMS = None


def _dims(path):
    global _DIMS
    if _DIMS is None:
        try:
            _DIMS = json.load(open(os.path.join(ROOT, "static/video/dims.json")))
        except Exception:
            _DIMS = {}
    if path in _DIMS:
        return tuple(_DIMS[path])
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                              "-of", "csv=p=0", os.path.join(ROOT, path)], capture_output=True, text=True).stdout.strip()
        w, h = out.split(",")[:2]
        return int(w), int(h)
    except Exception:
        return 1280, 720


def video_html(m):
    vid, cap = m.group(1), (m.group(2) or "").strip() or VIDEOS.get(m.group(1), "Фрагмент из работ студии НЕЙРОМЕДИА")
    return (f'<figure class="frame clip"><video class="lazyclip" muted loop playsinline preload="none" '
            f'poster="/static/video/{vid}-poster.webp" data-src="/static/video/{vid}.mp4" data-webm="/static/video/{vid}.webm" width="{_dims("static/video/"+vid+".mp4")[0]}" height="{_dims("static/video/"+vid+".mp4")[1]}"></video>'
            f'<figcaption>{html.escape(cap)}</figcaption></figure>')


CASES = {
    "niva": ("NIVA TRAVEL", "Имиджевый ролик с ощущением дорогой автомобильной съёмки: пустыня, закат, дрифт, пыль, крупные планы. Полностью на нейросетях, без реального продакшна.", "nivatravel"),
    "samokat": ("СИМ-КОНТРОЛЬ", "Кинематографичный ролик для национальной телематической платформы для кикшеринга. Собран полностью на нейросетях, от клиента понадобился только логотип.", "samokat"),
    "semen": ("Клиника «Семейная»", "Бренд-видео для сайта клиники. Клиент прислал обычные фото врачей, коридоров и оборудования, из них и собрали ролик.", "semen"),
}


def case_html(m):
    cid, note = m.group(1), (m.group(2) or "").strip()
    title, text, site_id = CASES[cid]
    w, h = _dims(f"static/video/{cid}-full.mp4")
    link = f"https://nmedia.pro/case?type=brands&id={site_id}"
    return (f'<figure class="case"><div class="case-head"><span class="kicker">Кейс студии</span><b>{html.escape(title)}</b>'
            f'<p>{html.escape(note or text)}</p></div>'
            f'<video controls playsinline preload="none" poster="/static/video/{cid}-full-poster.webp" width="{w}" height="{h}">'
            f'<source src="/static/video/{cid}-full.mp4" type="video/mp4"><source src="/static/video/{cid}-full.webm" type="video/webm"></video>'
            f'<figcaption><a href="{html.escape(link)}" rel="noopener">Смотреть кейс на сайте студии →</a></figcaption></figure>')


def showreel_block(slug):
    return (f'<section class="reel"><div class="reel-head"><div class="kicker">Шоурил студии</div>'
            f'<h2>Так выглядит ИИ-видео, которое мы делаем для брендов</h2>'
            f'<p>Все кадры созданы нейросетями, без съёмок. Этому процессу, от сценария до монтажа, мы и учим в курсе.</p></div>'
            f'<div class="reel-player"><video controls playsinline preload="none" poster="/static/video/showreel-poster.webp" width="{_dims("static/video/showreel.mp4")[0]}" height="{_dims("static/video/showreel.mp4")[1]}">'
            f'<source src="/static/video/showreel.mp4" type="video/mp4"><source src="/static/video/showreel.webm" type="video/webm"></video></div></section>')


def tg_url(slug, content, text=PROMO):
    """Ссылка в личку с заранее подставленным промокодом."""
    return utm(TG, slug, content) + "&text=" + urllib.parse.quote(text)


def cta_tg(slug):
    return (f'<div class="cta-inline magnet"><div class="t">'
            f'<b>Бесплатный урок из курса по промокоду «{PROMO}»</b>'
            f'<span>Напишите слово «{PROMO}» в Telegram, и я пришлю урок из «НЕЙРОМЕДИА Академии»: '
            f'как собрать рекламный ролик нейросетями, от первого кадра до монтажа. Без ботов и рассылок.</span></div>'
            f'<a class="btn" href="{html.escape(tg_url(slug, "magnet"))}">Забрать урок в Telegram</a></div>')


def cta_big(slug):
    return f'''<section class="cta-big">
<h2>Научитесь делать рекламное видео нейросетями за пару недель</h2>
<p>Курс от AI-студии НЕЙРОМЕДИА — мы делаем ролики для Ростеха, АвтоВАЗа, Кинопоиска и других брендов и учим тому же, что делаем на заказах. Без съёмок, команды и опыта в видео — нужен только ноутбук с браузером.</p>
<ul>
<li><b>9 900 ₽</b>«Сам»: 10 уроков от А до Я, все промпты и связки нейросетей</li>
<li><b>19 900 ₽</b>«С поддержкой»: проверка работ, разборы ошибок, чат с кураторами</li>
<li><b>29 900 ₽</b>«Под ключ»: учим находить клиентов, ведём до первого заказа</li>
</ul>
<div class="row"><a class="btn" href="{html.escape(utm(COURSE, slug, "final"))}">Выбрать тариф →</a>
<a class="btn ghost" href="{html.escape(tg_url(slug, "final_magnet"))}">Забрать бесплатный урок →</a></div>
</section>'''


def enrich(body_html, slug, meta=None):
    """Add ids to h2/h3, build TOC, extract FAQ, lazy images."""
    toc, faq = [], []
    used = set()

    def add_id(m):
        tag, inner = m.group(1), m.group(2)
        text = re.sub(r"<[^>]+>", "", inner)
        hid = slugify_ru(text) or "s"
        base, i = hid, 2
        while hid in used:
            hid = f"{base}-{i}"; i += 1
        used.add(hid)
        if tag == "h2":
            toc.append((hid, html.unescape(text)))
        return f'<{tag} id="{hid}">{inner}</{tag}>'

    body_html = re.sub(r"<(h[23])>(.*?)</\1>", add_id, body_html, flags=re.S)
    # FAQ: h3 questions after an h2 containing "вопрос"
    fm = re.search(r'<h2 id="[^"]*">[^<]*(?:вопрос|FAQ)[^<]*</h2>(.*?)(?=<h2|\Z)', body_html, re.S | re.I)
    if fm:
        for q, a in re.findall(r"<h3[^>]*>(.*?)</h3>\s*(.*?)(?=<h3|\Z)", fm.group(1), re.S):
            a_txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", a)).strip()
            a_txt = re.sub(r"\{\{[^}]+\}\}", "", a_txt).strip()
            if a_txt:
                faq.append((html.unescape(re.sub(r"<[^>]+>", "", q)), html.unescape(a_txt)))
    body_html = body_html.replace("<img ", '<img loading="lazy" decoding="async" ')
    n = [0]

    def rep_cta(_):
        n[0] += 1
        return cta_inline(slug, n[0], meta)
    body_html = re.sub(r"<p>\{\{cta_course\}\}</p>|\{\{cta_course\}\}", rep_cta, body_html)
    body_html = re.sub(r"<p>\{\{cta_tg\}\}</p>|\{\{cta_tg\}\}", lambda _: cta_tg(slug), body_html)
    body_html = re.sub(r"(?:<p>)?\{\{case:([a-z0-9-]+)(?:\|([^}]*))?\}\}(?:</p>)?", case_html, body_html)
    body_html = re.sub(r"(?:<p>)?\{\{video:([a-z0-9-]+)(?:\|([^}]*))?\}\}(?:</p>)?", video_html, body_html)
    body_html = re.sub(r"(?:<p>)?\{\{frame:([a-z0-9-]+)(?:\|([^}]*))?\}\}(?:</p>)?", frame_html, body_html)
    return body_html, toc, faq


def read_time(md):
    words = len(re.findall(r"\w+", md))
    return max(3, round(words / 180))


def metrika():
    if not METRIKA_ID:
        return ""
    return f'''<script>(function(m,e,t,r,i,k,a){{m[i]=m[i]||function(){{(m[i].a=m[i].a||[]).push(arguments)}};m[i].l=1*new Date();k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)}})(window,document,"script","https://mc.yandex.ru/metrika/tag.js","ym");ym({METRIKA_ID},"init",{{clickmap:true,trackLinks:true,accurateTrackBounce:true,webvisor:true}});</script><noscript><div><img src="https://mc.yandex.ru/watch/{METRIKA_ID}" style="position:absolute;left:-9999px" alt=""></div></noscript>'''


def head(title, desc, canonical, og_image=None, og_type="website", extra=""):
    og_img = og_image or f"{SITE}/static/og-default.png"
    verif = ""
    if os.environ.get("YANDEX_VERIFICATION"):
        verif += f'<meta name="yandex-verification" content="{os.environ["YANDEX_VERIFICATION"]}">'
    if os.environ.get("GOOGLE_VERIFICATION"):
        verif += f'<meta name="google-site-verification" content="{os.environ["GOOGLE_VERIFICATION"]}">'
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="{og_type}"><meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(desc)}"><meta property="og:url" content="{canonical}">
<meta property="og:image" content="{og_img}"><meta property="og:locale" content="ru_RU"><meta property="og:site_name" content="Блог {BRAND}">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="alternate" type="application/rss+xml" title="Блог {BRAND}" href="{SITE}/feed.xml">
<link rel="preload" href="/static/fonts/montserrat-400-cyrillic.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/static/fonts/fonts.css">
<link rel="stylesheet" href="/static/style.css?v={BUILD_V}">
{verif}{extra}{metrika()}
</head><body>'''


def header(slug="home"):
    return f'''<header class="hdr"><div class="wrap">
<a class="logo" href="/">{BRAND}<small>БЛОГ</small></a>
<nav class="nav"><a href="{utm(STUDIO, slug, "nav")}">Студия</a><a href="{utm(TG, slug, "nav")}">Telegram</a>
<a class="btn" href="{utm(COURSE, slug, "nav")}">Курс по ИИ-видео</a></nav></div></header>'''


def footer(slug="home"):
    y = datetime.date.today().year
    return f'''<footer class="ftr"><div class="wrap">
<div>© {y} {BRAND} — AI film studio<br>ИП Седов Н. С.</div>
<div class="links"><a href="{utm(STUDIO, slug, "footer")}">nmedia.pro</a><a href="{utm(COURSE, slug, "footer")}">Академия</a>
<a href="{utm(TG, slug, "footer")}">Telegram</a><a href="/feed.xml">RSS</a></div></div></footer>'''


CLIP_JS = """<script>(function(){var v=document.querySelectorAll('video.lazyclip');var t=document.createElement('video');var mp4=!!t.canPlayType('video/mp4; codecs="avc1.42E01E"');v.forEach(function(x){if(!mp4&&x.dataset.webm)x.dataset.src=x.dataset.webm});if(!('IntersectionObserver'in window)){v.forEach(function(x){x.src=x.dataset.src;x.play()});return}
var o=new IntersectionObserver(function(es){es.forEach(function(e){var x=e.target;if(e.isIntersecting){if(!x.src)x.src=x.dataset.src;x.play().catch(function(){})}else{x.pause()}})},{rootMargin:'200px'});v.forEach(function(x){o.observe(x)})})();</script>"""


COPY_JS = """<script>document.querySelectorAll('.body pre').forEach(function(p){var b=document.createElement('button');b.type='button';b.className='copy';b.textContent='Скопировать';b.onclick=function(){var t=p.querySelector('code')?p.querySelector('code').innerText:p.innerText;(navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).then(function(){b.textContent='Скопировано';setTimeout(function(){b.textContent='Скопировать'},1600)}).catch(function(){var r=document.createRange();r.selectNodeContents(p);var s=getSelection();s.removeAllRanges();s.addRange(r)});if(window.ym)try{ym(%s,'reachGoal','copy_prompt')}catch(e){}};p.appendChild(b)})</script>""" % METRIKA_ID


def sticky(slug):
    return f'''<div class="sticky-cta" id="sticky"><span>Курс по ИИ-видео<br><b style="color:#fff">11 уроков, от идеи до монтажа</b></span>
<a class="btn" href="{html.escape(utm(COURSE, slug, "sticky"))}">Программа →</a></div>
<script>(function(){{var s=document.getElementById('sticky');if(!s)return;document.body.classList.add('has-sticky');
var c=document.querySelector('.cta-inline'),st=c?c.getBoundingClientRect().top+scrollY:1500;
function f(){{var y=window.scrollY,h=document.body.scrollHeight-innerHeight;s.classList.toggle('show',y>st&&y<h-1400)}}
addEventListener('scroll',f,{{passive:true}});f();}})();</script>'''


def avatar_html():
    if os.path.exists(os.path.join(ROOT, AVATAR_FILE)):
        return f'<img class="av" src="/{AVATAR_FILE}" alt="{AUTHOR}" width="52" height="52">'
    return '<div class="av">НС</div>'


def hero_html(a, cover):
    hv = a.get("hero_video")
    alt = html.escape(a.get("h1", a["title"]))
    if not hv:
        return f'<figure class="cover"><img src="{cover}" width="1200" height="630" alt="{alt}" fetchpriority="high"></figure>'
    w, h = _dims(f"static/video/{hv}.mp4")
    cap = html.escape(a.get("hero_caption") or "Ролик AI-студии НЕЙРОМЕДИА")
    return (f'<figure class="cover hero-video"><video autoplay muted loop playsinline preload="auto" '
            f'poster="/static/video/{hv}-poster.webp" width="{w}" height="{h}" aria-label="{cap}">'
            f'<source src="/static/video/{hv}.mp4" type="video/mp4"><source src="/static/video/{hv}.webm" type="video/webm"></video>'
            f'<figcaption><span class="dot"></span>{cap}</figcaption></figure>')


def render_article(a, all_articles):
    AVATAR = avatar_html()
    slug = a["slug"]
    url = f"{SITE}/{slug}/"
    body_html, toc, faq = enrich(md_to_html(a["md"]), slug, a)
    cover = f"/{slug}/cover.png"
    cover_abs = f"{SITE}{cover}"
    date_iso = a.get("date")
    upd = a.get("updated", date_iso)
    cat = a.get("category", "obuchenie")
    rt = read_time(a["md"])
    ld = [{
        "@context": "https://schema.org", "@type": "Article", "headline": a.get("h1", a["title"]),
        "description": a["description"], "image": cover_abs, "datePublished": date_iso, "dateModified": upd,
        "author": {"@type": "Person", "name": AUTHOR, "jobTitle": AUTHOR_ROLE, "url": STUDIO},
        "publisher": {"@type": "Organization", "name": BRAND, "url": STUDIO},
        "mainEntityOfPage": url, "inLanguage": "ru",
        **({"abstract": " ".join(re.sub(r"\*\*|\[|\]\([^)]*\)", "", x) for x in [y.strip() for y in a.get("short", "").split("|")] if x)} if a.get("short") else {}),
    }, {
        "@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Блог", "item": SITE + "/"},
            {"@type": "ListItem", "position": 2, "name": CATEGORIES.get(cat, cat), "item": f"{SITE}/#{cat}"},
            {"@type": "ListItem", "position": 3, "name": a.get("h1", a["title"]), "item": url}]}]
    ld.append({"@context": "https://schema.org", "@type": "VideoObject", "name": "Шоурил AI-студии НЕЙРОМЕДИА",
               "description": "Рекламные и имиджевые ИИ-ролики студии НЕЙРОМЕДИА: все кадры созданы нейросетями.",
               "thumbnailUrl": f"{SITE}/static/video/showreel-poster.webp", "contentUrl": f"{SITE}/static/video/showreel.mp4",
               "uploadDate": "2026-09-01", "duration": "PT33S"})
    if faq:
        ld.append({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": ans}} for q, ans in faq]})
    extra = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in ld)
    extra += f'<meta property="article:published_time" content="{date_iso}">'
    toc_html = ""
    if len(toc) >= 3:
        toc_html = '<nav class="toc"><b>Содержание</b><ol>' + "".join(
            f'<li><a href="#{i}">{html.escape(t)}</a></li>' for i, t in toc) + "</ol></nav>"
    lead = a.get("lead", "")
    short = [x.strip() for x in a.get("short", "").split("|") if x.strip()]
    magnet_tail = "" if "{{cta_tg}}" in a["md"] else cta_tg(slug)
    tldr_html = ""
    if short:
        tldr_html = '<div class="tldr"><div class="tldr-h">Коротко</div><ul>' + "".join(
            f"<li>{inline_md(x)}</li>" for x in short) + "</ul></div>"
    upd_html = f' · обновлено <time datetime="{upd}">{ru_date(upd)}</time>' if upd and upd != date_iso else ""
    rel = [x for x in all_articles if x["slug"] != slug and x.get("category") == cat][:3]
    if len(rel) < 3:
        rel += [x for x in all_articles if x["slug"] != slug and x not in rel][:3 - len(rel)]
    rel_html = ""
    if rel:
        rel_html = '<section class="related"><h2>Читайте также</h2><div class="grid">' + "".join(card(x) for x in rel) + "</div></section>"
    page = head(a["title"], a["description"], url, cover_abs, "article", extra) + header(slug) + f'''
<main><div class="wrap">
<div class="crumbs"><a href="/">Блог</a> / <a href="/#{cat}">{CATEGORIES.get(cat, cat)}</a></div>
<div class="art-head"><div class="kicker">{CATEGORIES.get(cat, cat)}</div>
<h1>{html.escape(a.get("h1", a["title"]))}</h1>
{f'<p class="lead">{html.escape(lead)}</p>' if lead else ''}
<div class="author">{AVATAR}<div><b>{AUTHOR}</b>{AUTHOR_ROLE}<span class="creds">Делали ролики для <i>Ростеха</i>, <i>АвтоВАЗа</i>, <i>Кинопоиска</i></span><span class="when"><time datetime="{date_iso}">{ru_date(date_iso)}</time>{upd_html} · {rt} мин чтения</span></div></div></div>
{hero_html(a, cover)}
<article class="body">{tldr_html}{toc_html}{body_html}{magnet_tail}{showreel_block(slug)}{author_box(slug)}{cta_big(slug)}</article>
</div>{rel_html}</main>''' + footer(slug) + sticky(slug) + CLIP_JS + COPY_JS + "</body></html>"
    return page


def author_box(slug):
    return (f'<aside class="author-box"><img class="team" src="/static/media/team.webp" alt="Команда AI-студии НЕЙРОМЕДИА" loading="lazy"><div><b>{AUTHOR}</b>'
            f'<span>Основатель AI-студии {BRAND}. За последний год студия сделала рекламные и имиджевые ролики для Ростеха, АвтоВАЗа, Кинопоиска и других крупных брендов — '
            f'всё, о чём пишем в блоге, проверено на реальных заказах. <a href="{html.escape(utm(STUDIO, slug, "author"))}">Работы студии →</a></span></div></aside>')


def card(a):
    cat = a.get("category", "obuchenie")
    return (f'<a class="card" href="/{a["slug"]}/"><img src="/{a["slug"]}/cover.png" loading="lazy" width="1200" height="630" alt="">'
            f'<div class="in"><div class="meta"><span class="tag">{CATEGORIES.get(cat, cat)}</span><span>{ru_date(a["date"])}</span></div>'
            f'<h2>{html.escape(a.get("h1", a["title"]))}</h2><p>{html.escape(a["description"])}</p></div></a>')


def render_index(articles):
    cats = "".join(f'<a href="#{k}" data-cat="{k}">{v}</a>' for k, v in CATEGORIES.items())
    cards = "".join(card(a).replace('<a class="card"', f'<a class="card" data-cat="{a.get("category","obuchenie")}"', 1) for a in articles)
    title = "Блог НЕЙРОМЕДИА — как делать видео с помощью нейросетей"
    desc = "Практические разборы от AI-студии НЕЙРОМЕДИА: как делать рекламные ролики нейросетями, какие инструменты выбрать и как зарабатывать на ИИ-видео."
    ld = {"@context": "https://schema.org", "@type": "Blog", "name": "Блог НЕЙРОМЕДИА", "url": SITE + "/",
          "publisher": {"@type": "Organization", "name": BRAND, "url": STUDIO}}
    return head(title, desc, SITE + "/", extra=f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>') + header() + f'''
<main><div class="wrap"><section class="hero"><div class="kicker">Блог AI-студии {BRAND}</div>
<h1>Как делать видео нейросетями, которое продаёт</h1>
<p>Пишем о том, что делаем каждый день на заказах для Ростеха, АвтоВАЗа, Кинопоиска и других брендов: сценарии и промпты, генерация кадров, Kling и Seedance, звук, монтаж и как на этом зарабатывать.</p>
<div class="strip">{"".join(f'<img src="{MEDIA[i]["src"]}" alt="{html.escape(MEDIA[i]["alt"])}" loading="lazy">' for i in ["perfume-bubble","astronaut","car-road","singer-studio","whale"])}</div>
<div class="trust">Делали ролики для <b>Ростех</b><b>АвтоВАЗ</b><b>Кинопоиск</b></div>
<div class="cats"><a href="#" data-cat="" class="on">Все статьи</a>{cats}</div></section>
<div class="grid" id="grid">{cards}</div>
{showreel_block("home")}{cta_big("home")}</div></main>
<script>(function(){{var L=document.querySelectorAll('.cats a'),C=document.querySelectorAll('#grid .card');
function go(c){{L.forEach(function(a){{a.classList.toggle('on',a.dataset.cat===c)}});C.forEach(function(x){{x.style.display=!c||x.dataset.cat===c?'':'none'}})}}
L.forEach(function(a){{a.addEventListener('click',function(e){{e.preventDefault();go(a.dataset.cat);history.replaceState(null,'',a.dataset.cat?'#'+a.dataset.cat:'/')}})}});
if(location.hash)go(location.hash.slice(1));}})();</script>''' + footer() + "</body></html>"


def render_404():
    return head("Страница не найдена — Блог НЕЙРОМЕДИА", "Такой страницы нет", SITE + "/404.html") + header() + f'''
<main class="wrap" style="padding:90px 20px"><div class="kicker">404</div><h1 style="font-size:44px">Такой страницы нет</h1>
<p>Зато есть <a href="/">все статьи блога</a> и <a href="{utm(COURSE, "404", "404")}">курс по ИИ-видео</a>.</p></main>''' + footer() + "</body></html>"


def sitemap(articles):
    items = [f"<url><loc>{SITE}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>"]
    for a in articles:
        items.append(f"<url><loc>{SITE}/{a['slug']}/</loc><lastmod>{a.get('updated', a['date'])}</lastmod><priority>0.8</priority></url>")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(items) + "</urlset>"


def rss(articles):
    def rfc(d):
        return datetime.datetime.fromisoformat(d + "T09:00:00+03:00").strftime("%a, %d %b %Y %H:%M:%S +0300")
    items = "".join(
        f"<item><title>{html.escape(a.get('h1', a['title']))}</title><link>{SITE}/{a['slug']}/</link>"
        f"<guid>{SITE}/{a['slug']}/</guid><pubDate>{rfc(a['date'])}</pubDate><description>{html.escape(a['description'])}</description></item>"
        for a in articles[:30])
    return (f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Блог {BRAND}</title><link>{SITE}/</link>'
            f'<description>Как делать видео с помощью нейросетей</description><language>ru</language>{items}</channel></rss>')


AVATAR_FILE = "static/media/nikita.webp"
BUILD_V = datetime.datetime.now().strftime("%Y%m%d%H%M")


def build(include_drafts=False, out="dist"):
    dist = os.path.join(ROOT, out)
    shutil.rmtree(dist, ignore_errors=True)
    os.makedirs(dist)
    shutil.copytree(os.path.join(ROOT, "static"), os.path.join(dist, "static"))
    rootdir = os.path.join(ROOT, "root")
    if os.path.isdir(rootdir):
        for fn in os.listdir(rootdir):
            shutil.copy(os.path.join(rootdir, fn), os.path.join(dist, fn))
    arts = [parse(os.path.join(ROOT, "content/articles", f)) for f in sorted(os.listdir(os.path.join(ROOT, "content/articles"))) if f.endswith(".md")]
    arts = [a for a in arts if include_drafts or a.get("status", "draft") == "published"]
    today = datetime.date.today().isoformat()
    arts = [a for a in arts if include_drafts or a["date"] <= today]
    arts.sort(key=lambda a: a["date"], reverse=True)
    for a in arts:
        d = os.path.join(dist, a["slug"])
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "index.html"), "w", encoding="utf-8").write(render_article(a, arts))
        src_cover = os.path.join(ROOT, "content/covers", a["slug"] + ".png")
        if os.path.exists(src_cover):
            shutil.copy(src_cover, os.path.join(d, "cover.png"))
        img_dir = os.path.join(ROOT, "content/img", a["slug"])
        if os.path.isdir(img_dir):
            shutil.copytree(img_dir, os.path.join(d, "img"))
    open(os.path.join(dist, "index.html"), "w", encoding="utf-8").write(render_index(arts))
    open(os.path.join(dist, "404.html"), "w", encoding="utf-8").write(render_404())
    open(os.path.join(dist, "sitemap.xml"), "w", encoding="utf-8").write(sitemap(arts))
    open(os.path.join(dist, "feed.xml"), "w", encoding="utf-8").write(rss(arts))
    open(os.path.join(dist, "robots.txt"), "w", encoding="utf-8").write(
        f"User-agent: *\nAllow: /\nDisallow: /_preview/\nClean-param: utm_source&utm_medium&utm_campaign&utm_content\n\nSitemap: {SITE}/sitemap.xml\n")
    print(f"built {len(arts)} articles -> {dist}")
    return arts


if __name__ == "__main__":
    build(include_drafts="--drafts" in sys.argv, out="preview" if "--drafts" in sys.argv else "dist")
