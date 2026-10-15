#!/usr/bin/env python3
"""Публикация блога blog.nmedia.pro через GitHub Pages.

  python3 tools/publish_gh.py          # собрать, залить в репозиторий, проверить, IndexNow
  python3 tools/publish_gh.py --dry    # только сборка и проверки, без коммита

Что делает:
  1. build.py собирает сайт в dist/
  2. tools/check.py pre dist  -> если падает, публикация останавливается
  3. содержимое dist/ зеркалится в docs/ (GitHub Pages отдаёт из main /docs)
  4. docs/CNAME проставляется в blog.nmedia.pro, docs/.nojekyll создаётся
  5. git add -A, commit, push в main
  6. ждёт, пока GitHub Pages выложит изменения, проверяет живые страницы
  7. шлёт адреса в IndexNow через api.indexnow.org

Ключей и секретов тут нет. Запись в GitHub идёт по доступу сессии.
"""
import json, os, shutil, ssl, subprocess, sys, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import build

DOMAIN = "blog.nmedia.pro"
DOCS = os.path.join(ROOT, "docs")
DIST = os.path.join(ROOT, "dist")
CA = "/root/.ccr/ca-bundle.crt"


def sh(*args, **kw):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, **kw)


def mirror(src, dst):
    """Делает dst точной копией src. Возвращает (добавлено/изменено, удалено)."""
    keep = set()
    changed = 0
    for base, _, files in os.walk(src):
        rel = os.path.relpath(base, src)
        out = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(out, exist_ok=True)
        for f in files:
            s, d = os.path.join(base, f), os.path.join(out, f)
            keep.add(os.path.relpath(d, dst))
            if not os.path.exists(d) or os.path.getsize(s) != os.path.getsize(d) \
               or open(s, "rb").read() != open(d, "rb").read():
                shutil.copy2(s, d)
                changed += 1
    removed = 0
    for base, _, files in os.walk(dst, topdown=False):
        for f in files:
            rel = os.path.relpath(os.path.join(base, f), dst)
            if rel in ("CNAME", ".nojekyll") or rel in keep:
                continue
            os.remove(os.path.join(base, f))
            removed += 1
        if base != dst and not os.listdir(base):
            os.rmdir(base)
    return changed, removed


def indexnow(urls):
    key_file = os.path.join(ROOT, "indexnow.key")
    if not os.path.isfile(key_file):
        return "нет indexnow.key, пропускаю"
    key = open(key_file).read().strip()
    body = json.dumps({"host": DOMAIN, "key": key,
                       "keyLocation": f"https://{DOMAIN}/{key}.txt",
                       "urlList": urls}, ensure_ascii=False).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body,
                                 method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    ctx = ssl.create_default_context(cafile=CA) if os.path.exists(CA) else None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
                return f"HTTP {r.status}"
        except urllib.error.HTTPError as e:
            return f"HTTP {e.code} {e.read()[:200]!r}"
        except Exception as e:
            if attempt == 2:
                return f"не отправлено: {type(e).__name__}"
            time.sleep(4)


def live(url, timeout=25):
    ctx = ssl.create_default_context(cafile=CA) if os.path.exists(CA) else None
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "nmedia-publish"})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:
        return 0, str(e).encode()


def main():
    dry = "--dry" in sys.argv

    arts = build.build()
    slugs = [a["slug"] for a in arts]
    print(f"собрано статей: {len(arts)}")

    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools/check.py"), "pre", DIST])
    if r.returncode:
        print("СТОП: проверки до публикации не прошли, ничего не залито")
        sys.exit(1)

    if dry:
        print("--dry: остановился после проверок")
        return

    os.makedirs(DOCS, exist_ok=True)
    changed, removed = mirror(DIST, DOCS)
    open(os.path.join(DOCS, "CNAME"), "w").write(DOMAIN + "\n")
    open(os.path.join(DOCS, ".nojekyll"), "w").write("")
    print(f"в docs обновлено файлов: {changed}, удалено: {removed}")

    if not sh("git", "rev-parse", "--git-dir").returncode == 0:
        print("СТОП: это не git-репозиторий")
        sys.exit(1)

    sh("git", "add", "-A")
    st = sh("git", "status", "--porcelain")
    if not st.stdout.strip():
        print("изменений нет, коммит не нужен")
    else:
        n = len(st.stdout.strip().split("\n"))
        msg = "публикация блога: %d файлов" % n
        c = sh("git", "-c", "user.email=westjasmine2112001@gmail.com",
               "-c", "user.name=neyropenuc", "commit", "-m", msg)
        if c.returncode:
            print("СТОП: коммит не прошёл\n" + (c.stderr or c.stdout)[:500])
            sys.exit(1)
        p = sh("git", "push", "origin", "HEAD:refs/heads/main")
        if p.returncode:
            print("СТОП: push не прошёл\n" + (p.stderr or p.stdout)[:500])
            print("Если это 403 про authorized repository set, репозиторий не "
                  "добавлен в источники этой сессии. Скажи об этом Никите.")
            sys.exit(1)
        print(f"запушено: {n} файлов")

    print("жду, пока GitHub Pages выложит (до 3 минут)...")
    target = [f"https://{DOMAIN}/"] + [f"https://{DOMAIN}/{s}/" for s in slugs]
    ok = False
    for i in range(18):
        time.sleep(10)
        code, _ = live(target[0])
        if code == 200:
            ok = True
            break
    if not ok:
        print("ВНИМАНИЕ: главная страница пока не отвечает 200. Это нормально "
              "сразу после смены DNS или первой настройки Pages. Файлы в "
              "репозитории уже лежат, проверь вкладку Actions в репозитории.")

    bad = [u for u in target if live(u)[0] != 200]
    if bad:
        print("не открылись (%d): %s" % (len(bad), ", ".join(bad[:5])))
    else:
        print("живой сайт: все %d страниц отдают 200" % len(target))

    print("indexnow:", indexnow(target))


if __name__ == "__main__":
    main()
