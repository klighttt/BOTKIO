import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import hmac
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import sqlite3
from threading import Lock, BoundedSemaphore
import time
import unicodedata
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
PAGE = ROOT.parent / "app/src/main/assets/index.html"
COOKIE = "mood_session"
LIFETIME = 30 * 24 * 3600
MAX_BODY = 32768
MAX_USAGE_INTERVAL_MS = 15000
KDF_SLOTS = BoundedSemaphore(2)
ATTEMPTS = {}
ATTEMPT_LOCK = Lock()
ACTIONS = {
    "open_home", "open_settings", "open_history", "open_profile", "open_support",
    "answer_question", "previous_question",
}


class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def audit(db, user, action):
    db.execute("INSERT INTO activity(user_id,action,created_at) VALUES(?,?,?)",
               (user, action, now()))


def kdf(password, salt):
    with KDF_SLOTS:
        return hashlib.scrypt(password.encode(), salt=salt, n=2**17, r=8, p=1,
                              maxmem=192 * 1024**2, dklen=32)


def password_hash(password):
    salt = secrets.token_bytes(16)
    return f"scrypt:v1:{salt.hex()}:{kdf(password, salt).hex()}"


def matches(password, stored):
    _, _, salt, value = stored.split(":")
    return hmac.compare_digest(kdf(password, bytes.fromhex(salt)), bytes.fromhex(value))


def token_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def login_parts(value):
    if not isinstance(value, str):
        raise APIError(400, "Введите логин.")
    login = unicodedata.normalize("NFKC", value).strip()
    if not re.fullmatch(r"[\w.-]{1,40}", login):
        raise APIError(400, "Логин: до 40 букв, цифр и знаков . _ -.")
    return login, login.casefold()


def field(data, name, maximum):
    value = data.get(name)
    if not isinstance(value, str) or len(value) > maximum:
        raise APIError(400, "Неверное значение поля.")
    return value


def limit_auth(ip):
    current = time.monotonic()
    with ATTEMPT_LOCK:
        for key in tuple(ATTEMPTS):
            if ATTEMPTS[key][0] <= current:
                del ATTEMPTS[key]
        end, count = ATTEMPTS.get(ip, (current + 60, 0))
        if count >= 12:
            raise APIError(429, "Слишком много попыток. Подождите минуту.")
        ATTEMPTS[ip] = (end, count + 1)


@contextmanager
def connection(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def rows(db, sql, params=()):
    return [dict(row) for row in db.execute(sql, params)]


def messages(db, user):
    return rows(db, "SELECT id,text,sender,created_at FROM messages WHERE user_id=? ORDER BY id", (user,))


def result(db, user):
    row = db.execute("SELECT date,score,note FROM results WHERE user_id=?", (user,)).fetchone()
    return dict(row) if row else None


def add_message(db, user, value, sender):
    if not value.strip():
        raise APIError(400, "Введите сообщение.")
    cur = db.execute("INSERT INTO messages(user_id,text,sender,created_at) VALUES(?,?,?,?)",
                     (user, value, sender, now()))
    return dict(db.execute("SELECT id,text,sender,created_at FROM messages WHERE id=?",
                           (cur.lastrowid,)).fetchone())


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def handle_request(self, method):
        try:
            path = urlsplit(self.path).path
            if self.headers.get("Host") not in self.server.hosts:
                raise APIError(403, "Недопустимый адрес сервера.")
            if path == "/" and method == "GET":
                self.respond(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                return
            if not path.startswith("/api/"):
                raise APIError(404, "Страница не найдена.")
            data = self.read_post() if method == "POST" else {}
            with connection(self.server.db_path) as db:
                payload, cookie = self.route(db, method, path, data)
            self.json_response(200, payload, cookie)
        except APIError as error:
            self.json_response(error.status, {"error": error.message})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except Exception:
            import traceback
            traceback.print_exc()
            self.json_response(500, {"error": "Ошибка сервера. Повторите позже."})

    def read_post(self):
        origin = self.headers.get("Origin")
        if (origin and origin not in self.server.origins) or self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise APIError(403, "Запрос с другого сайта отклонён.")
        if self.headers.get_content_type() != "application/json" or self.headers.get("X-Mood-Request") != "1":
            raise APIError(415, "Ожидается JSON-запрос приложения.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                raise APIError(413, "Недопустимый размер запроса.")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (ValueError, UnicodeError):
            raise APIError(400, "Неверный JSON.")

    def session(self, db):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return None, None
        item = cookie.get(COOKIE)
        if not item or not re.fullmatch(r"[\w-]{43}", item.value, re.ASCII):
            return None, None
        digest = token_digest(item.value)
        user = db.execute(
            """SELECT u.id,u.login,u.style,u.is_admin,s.admin_open FROM sessions s
               JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?""",
            (digest, int(time.time()))).fetchone()
        return user, digest

    def session_cookie(self, token="", age=0):
        secure = "; Secure" if self.server.secure else ""
        return f"{COOKIE}={token}; Max-Age={age}; Path=/; HttpOnly; SameSite=Strict{secure}"

    def authenticate(self, db, path, data):
        limit_auth(self.client_address[0])
        login, key = login_parts(data.get("login"))
        password = field(data, "password", 256)
        try:
            password.encode()
        except UnicodeError:
            raise APIError(400, "Пароль содержит недопустимые символы.")
        if len(password) < 6:
            raise APIError(400, "Пароль должен содержать минимум 6 символов.")
        if path == "/api/register":
            encoded = password_hash(password)
            try:
                cursor = db.execute(
                    "INSERT INTO users(login,login_key,password_hash,created_at) VALUES(?,?,?,?)",
                    (login, key, encoded, now()))
            except sqlite3.IntegrityError:
                raise APIError(409, "Этот логин уже занят.")
            user_id = cursor.lastrowid
            audit(db, user_id, "register")
        else:
            row = db.execute("SELECT id,password_hash FROM users WHERE login_key=?", (key,)).fetchone()
            valid = matches(password, row["password_hash"] if row else self.server.dummy_hash)
            if not row or not valid:
                if row:
                    audit(db, row["id"], "login_failed")
                    db.commit()
                raise APIError(401, "Неверный логин или пароль.")
            user_id = row["id"]
        _, old_digest = self.session(db)
        if old_digest:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (old_digest,))
        token = secrets.token_urlsafe(32)
        db.execute("DELETE FROM sessions WHERE expires<=?", (int(time.time()),))
        db.execute("INSERT INTO sessions(token_hash,user_id,expires) VALUES(?,?,?)",
                   (token_digest(token), user_id, int(time.time()) + LIFETIME))
        db.execute("UPDATE users SET last_login=? WHERE id=?", (now(), user_id))
        audit(db, user_id, "login")
        return {"ok": True}, self.session_cookie(token, LIFETIME)

    def route(self, db, method, path, data):
        if method == "POST" and path in ("/api/login", "/api/register"):
            return self.authenticate(db, path, data)
        user, digest = self.session(db)
        if method == "GET" and path == "/api/me" and user is None:
            return {"user": None}, None
        if user is None:
            raise APIError(401, "Войдите в аккаунт.")
        uid = user["id"]
        can_admin = bool(user["is_admin"] and user["admin_open"])
        if method == "GET" and path == "/api/me":
            return {"user": {"id": uid, "login": user["login"], "style": user["style"],
                             "admin": can_admin}, "result": result(db, uid)}, None
        if method == "POST" and path == "/api/logout":
            db.execute("DELETE FROM sessions WHERE token_hash=?", (digest,))
            audit(db, uid, "logout")
            return {"ok": True}, self.session_cookie()
        if method == "POST" and path == "/api/activity":
            action = field(data, "action", 40)
            if action not in ACTIONS:
                raise APIError(400, "Неизвестное действие.")
            audit(db, uid, action)
            return {"ok": True}, None
        if method == "POST" and path == "/api/usage":
            elapsed = data.get("elapsed_ms")
            if type(elapsed) is not int or not 0 <= elapsed <= MAX_USAGE_INTERVAL_MS:
                raise APIError(400, "Некорректный интервал активности.")
            current = time.time_ns() // 1_000_000
            db.execute(
                """INSERT INTO usage_time(user_id,total_ms,last_seen_ms) VALUES (?,0,?)
                   ON CONFLICT(user_id) DO UPDATE SET
                       total_ms=total_ms+min(?,max(0,excluded.last_seen_ms-last_seen_ms)),
                       last_seen_ms=max(last_seen_ms,excluded.last_seen_ms)""",
                (uid, current, elapsed),
            )
            return {"ok": True}, None
        if method == "POST" and path == "/api/score":
            values, day = data.get("answers"), field(data, "date", 10)
            if not isinstance(values, list) or len(values) != 7 or any(
                type(value) is not int or not 0 <= value <= 4 for value in values
            ):
                raise APIError(400, "Нужно семь ответов от 0 до 4.")
            try:
                if date.fromisoformat(day).isoformat() != day:
                    raise ValueError
            except ValueError:
                raise APIError(400, "Некорректная дата.")
            total = sum(4 - value if index in (1, 3, 5) else value for index, value in enumerate(values))
            score = (84 + 18 * total) // 56
            cur = db.execute("INSERT INTO results(user_id,date,score) VALUES(?,?,?) ON CONFLICT(user_id) DO NOTHING",
                             (uid, day, score))
            if cur.rowcount:
                audit(db, uid, "complete_survey")
            return {"result": result(db, uid)}, None
        if method == "POST" and path == "/api/note":
            note = field(data, "note", 500).strip()
            cur = db.execute("UPDATE results SET note=? WHERE user_id=?", (note, uid))
            if not cur.rowcount:
                raise APIError(409, "Сначала пройдите опрос.")
            audit(db, uid, "save_note" if note else "clear_note")
            return {"result": result(db, uid)}, None
        if method == "POST" and path == "/api/style":
            style = field(data, "style", 10)
            if style not in ("green", "lilac", "night"):
                raise APIError(400, "Неизвестный стиль.")
            db.execute("UPDATE users SET style=? WHERE id=?", (style, uid))
            audit(db, uid, "change_style")
            return {"style": style}, None
        if method == "GET" and path == "/api/messages":
            return {"messages": messages(db, uid)}, None
        if method == "POST" and path == "/api/messages":
            value = field(data, "text", 4000)
            if value == "5051":
                if not user["is_admin"]:
                    audit(db, uid, "admin_denied")
                    db.commit()
                    raise APIError(403, "У аккаунта нет прав администратора.")
                db.execute("UPDATE sessions SET admin_open=1 WHERE token_hash=?", (digest,))
                audit(db, uid, "admin_open")
                return {"admin": True}, None
            item = add_message(db, uid, value, "user")
            audit(db, uid, "send_message")
            return {"message": item}, None
        if path.startswith("/api/admin/"):
            if not can_admin:
                raise APIError(403, "Доступ запрещён.")
            if method == "GET" and path == "/api/admin/users":
                audit(db, uid, "admin_view_users")
                return {"users": rows(db, "SELECT id,login,created_at FROM users ORDER BY id")}, None
            target = re.fullmatch(r"/api/admin/users/([0-9]{1,18})", path)
            if method == "GET" and target:
                target_id = int(target[1])
                profile = db.execute(
                    "SELECT id,login,created_at,last_login FROM users WHERE id=?",
                    (target_id,)).fetchone()
                if profile is None:
                    raise APIError(404, "Пользователь не найден.")
                audit(db, uid, "admin_view_user")
                usage = db.execute("SELECT total_ms FROM usage_time WHERE user_id=?", (target_id,)).fetchone()
                return {"user": dict(profile), "messages": messages(db, target_id),
                        "result": result(db, target_id),
                        "usage_seconds": usage["total_ms"] // 1000 if usage else None}, None
        raise APIError(404, "Запрос не найден.")

    def json_response(self, status, payload, cookie=None):
        self.respond(status, json.dumps(payload, ensure_ascii=True).encode(),
                     "application/json; charset=utf-8", cookie)

    def respond(self, status, body, content_type, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                         "connect-src 'self'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)


def grant_existing_klight(db):
    migration = db.execute(
        "INSERT INTO applied_migrations(name) VALUES (?) ON CONFLICT DO NOTHING RETURNING name",
        ("grant_existing_klight_admin",),
    ).fetchone()
    if migration is None:
        return
    user = db.execute(
        """UPDATE users SET is_admin=1
           WHERE login_key=? AND is_admin=0 AND NOT EXISTS (
               SELECT 1 FROM activity WHERE user_id=users.id AND action='admin_revoked'
           )
           RETURNING id""",
        ("klight",),
    ).fetchone()
    if user is not None:
        audit(db, user["id"], "admin_granted")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=ROOT / "mood.sqlite3")
    parser.add_argument("--port", type=int, default=8080)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--grant-admin", metavar="LOGIN")
    action.add_argument("--revoke-admin", metavar="LOGIN")
    parser.add_argument("--https-origin", help="Публичный HTTPS-адрес за обратным прокси")
    args = parser.parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    with connection(args.db) as db:
        db.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
        if args.grant_admin is not None or args.revoke_admin is not None:
            value = args.grant_admin if args.grant_admin is not None else args.revoke_admin
            try:
                _, key = login_parts(value)
            except APIError as error:
                parser.error(error.message)
            admin = int(args.grant_admin is not None)
            row = db.execute("UPDATE users SET is_admin=? WHERE login_key=? RETURNING id", (admin, key)).fetchone()
            if row is None:
                parser.error("Сначала зарегистрируйте этот логин.")
            db.execute("UPDATE sessions SET admin_open=0 WHERE user_id=?", (row["id"],))
            audit(db, row["id"], "admin_granted" if admin else "admin_revoked")
            print("Роль обновлена.")
            return
        grant_existing_klight(db)
    origins = {f"http://{host}:{args.port}" for host in ("127.0.0.1", "localhost", "10.0.2.2")}
    if args.https_origin:
        origin = urlsplit(args.https_origin)
        if origin.scheme != "https" or not origin.netloc or origin.username or origin.path not in ("", "/") or origin.query or origin.fragment:
            parser.error("--https-origin должен содержать только HTTPS-адрес")
        origins.add(f"https://{origin.netloc}")
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        server.db_path = args.db
        server.origins = origins
        server.hosts = {urlsplit(origin).netloc for origin in origins}
        server.secure = bool(args.https_origin)
        server.dummy_hash = password_hash(secrets.token_urlsafe(24))
        print(f"http://127.0.0.1:{args.port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
