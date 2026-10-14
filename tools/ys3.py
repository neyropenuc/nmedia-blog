"""Minimal Yandex Object Storage client, stdlib only.

Два режима:
  1) есть /home/claude/.yc/credentials -> прямой S3 API с подписью SigV4 (ручные сессии);
  2) файла нет -> через Yandex Cloud Function (URL в tools/fn_url.txt или env YC_BLOG_FN_URL).
     Ключа нет ни в коде, ни в сессии: заголовок Authorization: Api-Key подставляет прокси Claude
     (API credential окружения для functions.yandexcloud.net).

Код сборки (build.py и tools/*.py из SKILL_CODE) лежит в скилле nmedia-blog-article и копируется
оттуда; pull его не скачивает и не перезаписывает, push не заливает. Через функцию ходят только данные.

CLI:
  python3 tools/ys3.py test   проверить доступ
  python3 tools/ys3.py pull   скачать исходники из nmedia-blog-src (и запомнить их версии)
  python3 tools/ys3.py push   залить обратно ТОЛЬКО то, что изменено или создано после pull
"""
import base64, configparser, datetime, hashlib, hmac, json, mimetypes, os, re, ssl, sys, time
import urllib.error, urllib.parse, urllib.request

ENDPOINT = "storage.yandexcloud.net"
REGION = "ru-central1"
SRC_BUCKET = "nmedia-blog-src"
PUBLIC = "https://blog.nmedia.pro"

_here = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_here)
MANIFEST = os.path.join(ROOT, ".sync_manifest.json")

# код берётся из скилла, а не из бакета
SKILL_CODE = {"build.py", "tools/ys3.py", "tools/publish.py", "tools/covers.py", "tools/check.py", "tools/fn_url.txt"}

_CRED = "/home/claude/.yc/credentials"
AK = SK = None
if os.path.isfile(_CRED):
    _cfg = configparser.ConfigParser()
    _cfg.read(_CRED)
    AK = _cfg["default"]["aws_access_key_id"]
    SK = _cfg["default"]["aws_secret_access_key"]
_fn_file = os.path.join(_here, "fn_url.txt")
FN_URL = os.environ.get("YC_BLOG_FN_URL") or (open(_fn_file).read().strip() if os.path.isfile(_fn_file) else "")
MODE = "s3" if AK else "fn"

_ctx = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE", "/root/.ccr/ca-bundle.crt"))
_opener = urllib.request.build_opener(urllib.request.ProxyHandler(), urllib.request.HTTPSHandler(context=_ctx))

CT = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "application/javascript",
    ".xml": "application/xml; charset=utf-8", ".txt": "text/plain; charset=utf-8", ".svg": "image/svg+xml",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".json": "application/json", ".ico": "image/x-icon", ".woff2": "font/woff2", ".md": "text/markdown; charset=utf-8",
    ".csv": "text/csv; charset=utf-8", ".py": "text/x-python; charset=utf-8", ".mp4": "video/mp4", ".webm": "video/webm",
}
SKIP_DIRS = {"preview", "preview_pub", "dist", "src_media", "__pycache__", ".git"}
FN_MAX = 2_400_000  # лимит тела запроса/ответа Cloud Functions с запасом на base64


def md5(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


def _etag(e):
    return e.replace("&quot;", "").replace("&#34;", "").strip('"')


# ---------- режим s3: SigV4 ----------
def _sign(key, msg):
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def request(method, bucket="", key="", query=None, body=b"", headers=None):
    if MODE != "s3":
        raise RuntimeError("request() доступен только с ключом; в режиме функции используйте list_objects/get_object/put_file")
    headers = dict(headers or {})
    query = query or {}
    now = datetime.datetime.utcnow()
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date = now.strftime("%Y%m%d")
    path = "/"
    if bucket:
        path += bucket
        if key:
            path += "/" + urllib.parse.quote(key, safe="/-_.~")
    payload_hash = hashlib.sha256(body).hexdigest()
    headers["host"] = ENDPOINT
    headers["x-amz-date"] = amz_date
    headers["x-amz-content-sha256"] = payload_hash
    canon_q = "&".join(
        f"{urllib.parse.quote(k, safe='-_.~')}={urllib.parse.quote(str(v), safe='-_.~')}"
        for k, v in sorted(query.items()))
    lower = {k.lower(): str(v).strip() for k, v in headers.items()}
    signed = ";".join(sorted(lower))
    canon_h = "".join(f"{k}:{lower[k]}\n" for k in sorted(lower))
    creq = "\n".join([method, path, canon_q, canon_h, signed, payload_hash])
    scope = f"{date}/{REGION}/s3/aws4_request"
    sts = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(creq.encode()).hexdigest()])
    k = _sign(_sign(_sign(_sign(("AWS4" + SK).encode(), date), REGION), "s3"), "aws4_request")
    sig = hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()
    headers["Authorization"] = f"AWS4-HMAC-SHA256 Credential={AK}/{scope}, SignedHeaders={signed}, Signature={sig}"
    url = f"https://{ENDPOINT}{path}" + (f"?{canon_q}" if canon_q else "")
    for attempt in range(4):
        req = urllib.request.Request(url, data=body if method in ("PUT", "POST") else None, method=method)
        for hk, hv in headers.items():
            if hk != "host":
                req.add_header(hk, hv)
        try:
            with _opener.open(req, timeout=120) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


# ---------- режим fn: Cloud Function ----------
def fn_call(obj):
    if not FN_URL:
        raise RuntimeError("нет ключа и не задан URL функции (tools/fn_url.txt или YC_BLOG_FN_URL)")
    data = json.dumps(obj).encode()
    for attempt in range(4):
        req = urllib.request.Request(FN_URL, data=data, method="POST", headers={"Content-Type": "application/json"})
        try:
            with _opener.open(req, timeout=120) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                return e.code, json.loads(body)
            except Exception:
                return e.code, {"error": body[:300].decode(errors="replace")}
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


# ---------- общее API ----------
def list_objects(bucket, prefix=""):
    """-> [{key, size, etag}]"""
    out, tok = [], None
    while True:
        if MODE == "fn":
            st, r = fn_call({"op": "list", "bucket": bucket, "prefix": prefix, "token": tok})
            if st != 200:
                raise RuntimeError(f"list {bucket}: {st} {r}")
            out += [{"key": i["key"], "size": i["size"], "etag": _etag(i["etag"])} for i in r["items"]]
            tok = r.get("next")
        else:
            q = {"list-type": "2"}
            if prefix:
                q["prefix"] = prefix
            if tok:
                q["continuation-token"] = tok
            st, b = request("GET", bucket, query=q)
            if st != 200:
                raise RuntimeError(f"list {bucket}: {st} {b[:200]}")
            x = b.decode()
            out += [{"key": k, "etag": _etag(e), "size": int(z)}
                    for k, e, z in re.findall(r"<Key>(.*?)</Key>.*?<ETag>(.*?)</ETag>.*?<Size>(\d+)</Size>", x, re.S)]
            m = re.search(r"<NextContinuationToken>(.*?)</NextContinuationToken>", x)
            tok = m.group(1) if m else None
        if not tok:
            return out


def get_object(bucket, key):
    if MODE == "s3":
        st, b = request("GET", bucket, key)
        if st != 200:
            raise RuntimeError(f"get {key}: {st}")
        return b
    st, r = fn_call({"op": "get", "bucket": bucket, "key": key})
    if st == 200:
        return base64.b64decode(r["b64"])
    if st == 413:  # большие видео: те же файлы лежат на публичном сайте
        try:
            with _opener.open(f"{PUBLIC}/{urllib.parse.quote(key)}", timeout=300) as resp:
                return resp.read()
        except Exception as e:
            raise FileNotFoundError(f"{key}: большой файл, публичная копия недоступна ({e})")
    raise RuntimeError(f"get {key}: {st} {r}")


def put_file(bucket, local, key):
    ext = os.path.splitext(local)[1].lower()
    ct = CT.get(ext) or mimetypes.guess_type(local)[0] or "application/octet-stream"
    cache = "public, max-age=300" if ext in (".html", ".xml", ".txt") else "public, max-age=2592000"
    with open(local, "rb") as f:
        body = f.read()
    if MODE == "s3":
        return request("PUT", bucket, key, body=body, headers={"Content-Type": ct, "Cache-Control": cache})
    if len(body) > FN_MAX:
        return 413, f"{key}: файл больше {FN_MAX // 1_000_000} МБ, через функцию не загрузить".encode()
    st, r = fn_call({"op": "put", "bucket": bucket, "key": key, "b64": base64.b64encode(body).decode(),
                     "ctype": ct, "cache": cache})
    return st, json.dumps(r).encode()


def sync_dir(bucket, root, skip_dirs=()):
    """Сайт: заливает папку, пропуская файлы с тем же md5, что уже в бакете."""
    remote = {it["key"]: it["etag"] for it in list_objects(bucket)}
    n = 0
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in skip_dirs]
        for fn in files:
            p = os.path.join(d, fn)
            key = os.path.relpath(p, root).replace(os.sep, "/")
            if remote.get(key) == md5(p):
                continue
            st, body = put_file(bucket, p, key)
            if st != 200:
                print("FAIL", key, st, body[:300])
            n += 1
    return n


def pull(root=ROOT):
    """Скачивает исходники (без кода из SKILL_CODE); запоминает md5 каждого файла в .sync_manifest.json."""
    man, n = {}, 0
    for it in list_objects(SRC_BUCKET):
        k = it["key"]
        if k.endswith("/") or k.startswith("src_media/") or k in SKILL_CODE:
            continue
        p = os.path.join(root, k)
        if not (os.path.isfile(p) and md5(p) == it["etag"]):
            try:
                data = get_object(SRC_BUCKET, k)
            except FileNotFoundError as e:
                print("пропущен (не нужен для сборки, на сайте уже лежит):", e)
                continue
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").write(data)
            n += 1
        man[k] = it["etag"]
    json.dump(man, open(MANIFEST, "w"), indent=0)
    return n


def push(root=ROOT, force=False):
    """Заливает только изменённые или новые файлы (относительно последнего pull).
    Если файл в бакете за это время поменял кто-то другой, не перезаписывает его."""
    if not os.path.isfile(MANIFEST) and not force:
        raise SystemExit("нет .sync_manifest.json: сначала python3 tools/ys3.py pull")
    man = json.load(open(MANIFEST)) if os.path.isfile(MANIFEST) else {}
    remote = {it["key"]: it["etag"] for it in list_objects(SRC_BUCKET)}
    n = 0
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".")]
        for fn in files:
            if fn.startswith("."):
                continue
            p = os.path.join(d, fn)
            k = os.path.relpath(p, root).replace(os.sep, "/")
            if k in SKILL_CODE:
                continue
            h = md5(p)
            if man.get(k) == h or remote.get(k) == h:
                continue
            if k in remote and k in man and remote[k] != man[k] and not force:
                print("КОНФЛИКТ, пропущен (в бакете новее):", k)
                continue
            st, body = put_file(SRC_BUCKET, p, k)
            if st != 200:
                print("FAIL", k, st, body[:300])
            else:
                man[k] = h
                n += 1
                print("up", k)
    json.dump(man, open(MANIFEST, "w"), indent=0)
    return n


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    print("mode:", MODE)
    if cmd == "pull":
        print("downloaded", pull())
    elif cmd == "push":
        print("uploaded", push(force="--force" in sys.argv))
    else:
        print(len(list_objects(SRC_BUCKET)), "objects in", SRC_BUCKET)
