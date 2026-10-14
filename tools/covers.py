#!/usr/bin/env python3
"""Render branded 1200x630 covers for articles (and og-default) with Playwright."""
import html, os, re, sys
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from build import parse, CATEGORIES  # noqa

FONT_DIR = os.path.join(ROOT, "static/fonts")


def font_css():
    import base64
    css = open(os.path.join(FONT_DIR, "fonts.css")).read().replace("'Montserrat'", "M")
    def emb(m):
        data = base64.b64encode(open(os.path.join(FONT_DIR, m.group(1)), "rb").read()).decode()
        return f"url(data:font/woff2;base64,{data})"
    return re.sub(r"url\(/static/fonts/([^)]+)\)", emb, css)


def data_uri(path):
    import base64
    return "data:image/webp;base64," + base64.b64encode(open(path, "rb").read()).decode()


def cover_html(kicker, title, variant=0, image=None):
    accents = ["#c0e800", "#c0e800", "#c0e800"]
    acc = accents[variant % 3]
    # film-frame decoration: grid of frames on the right
    frames = "".join(
        f'<div class="fr" style="animation:none;opacity:{0.10 + ((i * 7 + variant * 3) % 5) * 0.07}"></div>' for i in range(12))
    return f'''<!doctype html><html><head><meta charset="utf-8"><style>
{font_css()}
*{{margin:0;box-sizing:border-box}}
body{{width:1200px;height:630px;background:#0b0b0b;font-family:M,"DejaVu Sans",sans-serif;color:#fff;position:relative;overflow:hidden}}
.glow{{position:absolute;right:-220px;top:-220px;width:760px;height:760px;border-radius:50%;background:radial-gradient(circle,rgba(192,232,0,.22),rgba(192,232,0,0) 62%)}}
.grid{{position:absolute;right:48px;top:48px;display:grid;grid-template-columns:repeat(3,112px);gap:12px}}
.fr{{height:78px;border-radius:10px;border:1.5px solid {acc};}}
.in{{position:absolute;left:72px;top:64px;right:72px;bottom:64px;display:flex;flex-direction:column}}
.k{{font-size:22px;font-weight:700;letter-spacing:.2em;text-transform:uppercase;color:{acc}}}
.t{{margin-top:auto;font-size:{64 if len(title) < 48 else 54 if len(title) < 70 else 46}px;line-height:1.08;font-weight:800;max-width:920px;letter-spacing:-.01em}}
.t em{{font-style:normal;color:{acc}}}
.b{{margin-top:34px;display:flex;align-items:center;gap:16px;font-size:20px;font-weight:700;letter-spacing:.12em;color:#d8d8d8}}
.b i{{display:inline-block;width:38px;height:38px;border-radius:9px;background:{acc};color:#0b0b0b;font-style:normal;font-weight:800;display:grid;place-items:center;letter-spacing:0}}
.b span{{color:#8a8a8a;font-weight:600;letter-spacing:.04em}}
.bg{{position:absolute;inset:0 0 0 330px;background:url({data_uri(image) if image else ''}) center/cover}}
.shade{{position:absolute;inset:0;background:linear-gradient(90deg,#0b0b0b 30%,rgba(11,11,11,.86) 48%,rgba(11,11,11,.25) 75%,rgba(11,11,11,.1)),linear-gradient(0deg,rgba(11,11,11,.7),rgba(11,11,11,0) 45%)}}
.bar{{position:absolute;left:72px;top:0;width:90px;height:6px;background:{acc}}}
</style></head><body>{('<div class="bg"></div><div class="shade"></div><div class="bar"></div>') if image else ('<div class="glow"></div><div class="grid">'+frames+'</div>')}
<div class="in"><div class="k">{html.escape(kicker)}</div><div class="t">{title}</div>
<div class="b"><i>N</i>НЕЙРОМЕДИА <span>· blog.nmedia.pro</span></div></div></body></html>'''


def emphasize(title):
    """*word* in cover_title -> accent colour."""
    t = html.escape(title)
    return re.sub(r"\*(.+?)\*", r"<em>\1</em>", t)


def render(jobs):
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1200, "height": 630})
        for out, kicker, title, v, img in jobs:
            pg.set_content(cover_html(kicker, emphasize(title), v, img))
            pg.wait_for_timeout(150)
            pg.screenshot(path=out)
            print("cover", out)
        b.close()


if __name__ == "__main__":
    art_dir = os.path.join(ROOT, "content/articles")
    out_dir = os.path.join(ROOT, "content/covers")
    os.makedirs(out_dir, exist_ok=True)
    only = sys.argv[1:]
    jobs = []
    for i, f in enumerate(sorted(os.listdir(art_dir))):
        a = parse(os.path.join(art_dir, f))
        if only and a["slug"] not in only:
            continue
        jobs.append((os.path.join(out_dir, a["slug"] + ".png"),
                     a.get("cover_kicker") or CATEGORIES.get(a.get("category", ""), "Блог"),
                     a.get("cover_title") or a.get("h1") or a["title"], i,
                     os.path.join(ROOT, "static/media", a["cover_image"] + ".webp") if a.get("cover_image") else None))
    if not only:
        jobs.append((os.path.join(ROOT, "static/og-default.png"), "Блог AI-студии", "Как делать видео *нейросетями*, которое продаёт", 1,
                     os.path.join(ROOT, "static/media/astronaut.webp")))
    render(jobs)
