#!/usr/bin/env python3
"""Сколько раз каждый кадр из static/media/library.json уже использован.

Считает обложки (cover_image), кадры в тексте ({{frame:id|...}}) в content/articles
и картинки в постах для Дзена (dzen/*.txt). Выводит кадры от самых редких к самым частым,
чтобы для новой статьи или поста брать свежие картинки, а не одни и те же.

Запуск:
  python3 tools/media_usage.py            # таблица по всем кадрам
  python3 tools/media_usage.py --free 15  # 15 самых редких горизонтальных кадров (для обложек и Дзена)
  python3 tools/media_usage.py --tag спорт # только кадры с тегом
"""
import json, os, re, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
lib = json.load(open(os.path.join(ROOT, "static/media/library.json"), encoding="utf-8"))
ids = {i["id"] for i in lib}
cnt = collections.Counter()
where = collections.defaultdict(list)

art_dir = os.path.join(ROOT, "content/articles")
for f in sorted(os.listdir(art_dir)):
    t = open(os.path.join(art_dir, f), encoding="utf-8").read()
    found = re.findall(r"^cover_image:\s*([\w-]+)", t, re.M) + re.findall(r"\{\{frame:([\w-]+)", t)
    for i in found:
        cnt[i] += 1
        where[i].append(f[:-3])

dz_dir = os.path.join(ROOT, "dzen")
if os.path.isdir(dz_dir):
    for f in sorted(os.listdir(dz_dir)):
        t = open(os.path.join(dz_dir, f), encoding="utf-8").read()
        for i in re.findall(r"static/media/([\w-]+)\.webp", t):
            if i in ids:
                cnt[i] += 1
                where[i].append("dzen:" + f[:-4])

args = sys.argv[1:]
tag = args[args.index("--tag") + 1] if "--tag" in args else None
items = [i for i in lib if not tag or tag in i.get("tags", [])]
items.sort(key=lambda i: (cnt[i["id"]], i["id"]))

if "--free" in args:
    n = int(args[args.index("--free") + 1])
    hor = [i for i in items if i.get("w", 16) >= i.get("h", 9)]
    for i in hor[:n]:
        print(f'{cnt[i["id"]]:>3}  {i["id"]:<24} {i["alt"][:80]}')
    sys.exit(0)

for i in items:
    o = "V" if i.get("h", 9) > i.get("w", 16) else "H"
    print(f'{cnt[i["id"]]:>3} {o} {i["id"]:<24} [{", ".join(i.get("tags", []))}]')
