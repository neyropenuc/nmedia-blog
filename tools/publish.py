#!/usr/bin/env python3
"""Build -> pre-check -> upload -> post-check -> IndexNow.
  python3 tools/publish.py            # publish all articles with status: published and date <= today
  python3 tools/publish.py --dry      # build + checks only
"""
import os, sys, subprocess, json, urllib.request, ssl
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import build
from ys3 import sync_dir, request, put_file

BUCKET = "blog.nmedia.pro"
KEY = open(os.path.join(ROOT, "indexnow.key")).read().strip()


def indexnow(urls):
    body = json.dumps({"host": "blog.nmedia.pro", "key": KEY, "keyLocation": f"https://blog.nmedia.pro/{KEY}.txt",
                       "urlList": urls}).encode()
    ctx = ssl.create_default_context(cafile="/root/.ccr/ca-bundle.crt")
    req = urllib.request.Request("https://yandex.com/indexnow", data=body, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return f"{e.code} {e.read()[:200]}"


def main():
    dry = "--dry" in sys.argv
    arts = build.build()
    dist = os.path.join(ROOT, "dist")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools/check.py"), "pre", dist])
    if r.returncode:
        print("STOP: pre-check failed"); sys.exit(1)
    if dry:
        return
    # upload: html/xml last so assets are in place first
    n = sync_dir(BUCKET, dist)
    print("uploaded", n)
    slugs = [a["slug"] for a in arts]
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools/check.py"), "post"] + slugs)
    urls = ["https://blog.nmedia.pro/"] + [f"https://blog.nmedia.pro/{s}/" for s in slugs]
    print("indexnow:", indexnow(urls))
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
