"""freebuff-web: terminale web per usare la CLI di freebuff da browser (PC, telefono, Tailscale).
Non integrato con l'app nativa di freebuff: esegue il comando `freebuff` in una PTY.

Uso:
  python freebuffserver.py serve                     # avvia solo il server
  python freebuffserver.py open [cartella] [args...] # (comando `freebufft`) crea una sessione e apre il browser
"""
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
import uuid
import webbrowser
from pathlib import Path

HOST = "127.0.0.1"
PORT = int(os.environ.get("FREEBUFFT_PORT", "7681"))
BASE = f"http://{HOST}:{PORT}"
HERE = Path(__file__).parent
SHIM = HERE / "shim"
# opzioni che non aprono l'interfaccia: eseguite direttamente nella console
DIRECT_ARGS = {"-v", "--version", "-h", "--help"}


def real_freebuff():
    """Percorso del vero freebuff, saltando la cartella shim (evita la ricorsione)."""
    if os.environ.get("FREEBUFFT_CMD"):
        return os.environ["FREEBUFFT_CMD"]
    skip = {SHIM.resolve(), HERE.resolve()}
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d:
            continue
        try:
            if Path(d).resolve() in skip:
                continue
        except OSError:
            continue
        for ext in (".cmd", ".exe", ".bat"):
            p = Path(d) / ("freebuff" + ext)
            if p.is_file():
                return str(p)
    return "freebuff"


COMMAND = real_freebuff()


def tailscale_info():
    """Ritorna (ip, dnsname) di Tailscale, oppure (None, None)."""
    try:
        exe = "tailscale"
        if os.name == "nt" and os.path.exists(r"C:\Program Files\Tailscale\tailscale.exe"):
            exe = r"C:\Program Files\Tailscale\tailscale.exe"
        fl = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        out = subprocess.run([exe, "status", "--json"], capture_output=True, text=True,
                             timeout=5, creationflags=fl).stdout
        me = json.loads(out)["Self"]
        ip = next((a for a in me["TailscaleIPs"] if "." in a), None)
        return ip, (me.get("DNSName") or "").rstrip(".") or None
    except Exception:
        return None, None


def qr_ascii(text):
    import io
    import qrcode
    q = qrcode.QRCode(border=2)
    q.add_data(text)
    buf = io.StringIO()
    q.print_ascii(out=buf, invert=True)
    return buf.getvalue()


def qr_svg(text):
    import io
    import qrcode
    import qrcode.image.svg
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


def api(path, data=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=3) as r:
        return json.loads(r.read())


def client_open(cwd, args=()):
    if os.environ.get("FREEBUFFT_DIRECT") or DIRECT_ARGS & set(args):
        sys.exit(subprocess.call([COMMAND, *args], cwd=cwd))
    try:
        api("/api/ping")
    except Exception:
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        exe = sys.executable
        if os.name == "nt" and exe.lower().endswith("python.exe"):
            pw = exe[:-10] + "pythonw.exe"
            exe = pw if os.path.exists(pw) else exe
        subprocess.Popen([exe, str(Path(__file__).resolve()), "serve"],
                         creationflags=flags, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True)
        for _ in range(50):
            time.sleep(0.2)
            try:
                api("/api/ping")
                break
            except Exception:
                pass
        else:
            sys.exit("Impossibile avviare il server")
    s = api("/api/sessions", {"cwd": os.path.abspath(cwd), "args": list(args)})
    url = f"{BASE}/s/{s['id']}"
    lan = lan_ip()
    lan_url = f"http://{lan}:{PORT}/s/{s['id']}" if lan else None
    qr_url = s.get("ts_url") or lan_url
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if qr_url:
        try:
            print(f"\nScansiona per aprirlo ({'Tailscale' if s.get('ts_url') else 'rete locale'}):\n")
            print(qr_ascii(qr_url))
        except Exception as e:
            print(f"(QR non disponibile: {e})")
    print(f"Locale:    {url}")
    if lan_url:
        print(f"Rete:      {lan_url}")
    if s.get("ts_url"):
        print(f"Tailscale: {s['ts_url']}")
    webbrowser.open(qr_url or url)


def lan_ip():
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as so:
            so.connect(("192.0.2.1", 80))   # nessun pacchetto inviato, serve solo a scegliere l'interfaccia
            ip = so.getsockname()[0]
            return None if ip.startswith("127.") else ip
    except OSError:
        return None


# ---------------------------------------------------------------- server
def serve():
    from aiohttp import web, WSMsgType
    from winpty import PtyProcess

    sessions = {}  # id -> dict(proc, cwd, buf, clients)

    class Session:
        def __init__(self, cwd, args):
            self.id = uuid.uuid4().hex[:8]
            self.cwd = cwd
            self.args = args
            self.buf = bytearray()
            self.clients = set()
            self.size = (30, 120)          # (rows, cols) attuale della PTY
            self.wanted = {}               # ws -> (rows, cols) desiderati da ogni dispositivo
            self.active = None             # dispositivo che "comanda" la dimensione
            self.proc = PtyProcess.spawn([COMMAND, *args], cwd=cwd, dimensions=self.size)
            self.alive = True

        async def ctrl(self, ws, **msg):
            # messaggi di controllo: prefisso NUL, mai presente nell'output del terminale
            try:
                await ws.send_str("\x00" + json.dumps(msg))
            except Exception:
                self.clients.discard(ws)

        def setsize(self, rows, cols):
            try:
                self.proc.setwinsize(rows, cols)
            except Exception:
                pass

        async def activate(self, ws, force=False):
            """Il dispositivo ws diventa quello attivo: la PTY prende la sua dimensione."""
            if ws not in self.wanted:
                return
            if self.active is ws and not force:
                return
            self.active = ws
            size = self.wanted[ws]
            if size != self.size:
                self.size = size
                if self.alive:
                    self.setsize(*size)
            for c in list(self.clients):
                await self.ctrl(c, t="size", rows=size[0], cols=size[1], me=(c is ws))

        async def redraw(self):
            # piccolo "scossone" di dimensione: freebuff ridisegna tutto lo schermo
            if not self.alive:
                return
            r, c = self.size
            self.setsize(r, max(c - 1, 10))
            await asyncio.sleep(0.05)
            self.setsize(r, c)

        async def leave(self, ws):
            self.clients.discard(ws)
            self.wanted.pop(ws, None)
            if self.active is ws:
                self.active = None
                if self.wanted:
                    await self.activate(next(reversed(self.wanted)))

        async def pump(self):
            loop = asyncio.get_running_loop()
            while True:
                try:
                    data = await loop.run_in_executor(None, self.proc.read, 65536)
                except EOFError:
                    break
                except Exception:
                    break
                if not data:
                    if not self.proc.isalive():
                        break
                    continue
                self.buf += data.encode("utf-8", "replace")
                del self.buf[:-400000]
                for ws in list(self.clients):
                    try:
                        await ws.send_str(data)
                    except Exception:
                        self.clients.discard(ws)
            self.alive = False
            for ws in list(self.clients):
                try:
                    await ws.send_str("\r\n\x1b[2m[processo terminato]\x1b[0m\r\n")
                except Exception:
                    pass

    ts_ip, ts_dns = tailscale_info()

    def ts_url(sid=None):
        h = ts_dns or ts_ip
        if not h:
            return None
        return f"http://{h}:{PORT}/{'s/' + sid if sid else ''}"

    def is_local(req):
        return req.remote in ("127.0.0.1", "::1")

    async def ping(_):
        return web.json_response({"ok": True})

    async def create(req):
        body = await req.json()
        cwd = body.get("cwd") or os.getcwd()
        s = Session(cwd, [str(a) for a in body.get("args", [])])
        sessions[s.id] = s
        asyncio.create_task(s.pump())
        return web.json_response({"id": s.id, "ts_url": ts_url(s.id)})

    async def index(req):
        items = "".join(
            f'<li><a href="/s/{s.id}">{s.cwd}</a> <code>{" ".join(s.args)}</code> {"" if s.alive else "(terminata)"}</li>'
            for s in sessions.values()) or "<li>Nessuna sessione. Esegui <code>freebufft</code> in una cartella.</li>"
        qr = ""
        if ts_url() and is_local(req):
            qr = (f"<h3>Tailscale</h3><div style='background:#fff;width:220px;padding:4px'>"
                  f"{qr_svg(ts_url())}</div><p><code>{ts_url()}</code></p>")
        return web.Response(text=f"<body style='font-family:sans-serif;background:#111;color:#ddd'>"
                                 f"<h2>freebuffserver</h2><ul>{items}</ul>{qr}</body>", content_type="text/html")

    async def page(req):
        if req.match_info["id"] not in sessions:
            raise web.HTTPNotFound(text="Sessione non trovata (il server e' stato riavviato?)")
        return web.Response(text=(HERE / "terminal.html").read_text(encoding="utf-8"),
                            content_type="text/html", headers={"Cache-Control": "no-store"})

    async def ws_handler(req):
        s = sessions.get(req.match_info["id"])
        if not s:
            raise web.HTTPNotFound()
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(req)
        # prima la dimensione attuale (cosi' lo storico viene disegnato alla misura giusta), poi lo storico
        await s.ctrl(ws, t="size", rows=s.size[0], cols=s.size[1], me=False)
        if s.buf:
            await ws.send_str(s.buf.decode("utf-8", "replace"))
        s.clients.add(ws)
        first = True
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    m = json.loads(msg.data)
                except ValueError:
                    continue
                t = m.get("t")
                if t == "r":
                    s.wanted[ws] = (max(int(m["rows"]), 5), max(int(m["cols"]), 10))
                    if s.active is None or s.active is ws:
                        await s.activate(ws, force=True)
                    if first:          # nuovo dispositivo: schermo ridisegnato pulito
                        first = False
                        await s.redraw()
                elif t == "a":         # focus/tocco: questo dispositivo prende il comando
                    await s.activate(ws)
                elif t == "i" and s.alive:
                    await s.activate(ws)
                    s.proc.write(m["d"])
                elif t == "q" and s.alive:
                    # risposta automatica del terminale: solo dal dispositivo attivo, senza attivarlo
                    if s.active is ws or s.active is None:
                        s.proc.write(m["d"])
        finally:
            await s.leave(ws)
        return ws

    @web.middleware
    async def guard(req, handler):
        # anti DNS-rebinding/CSRF: host e origin devono essere i nostri
        # accesso libero da qualsiasi IP; si blocca solo l'uso da pagine di altri siti
        origin = req.headers.get("Origin")
        if origin and origin.split("://", 1)[-1] != req.host:
            raise web.HTTPForbidden()
        return await handler(req)

    app = web.Application(middlewares=[guard])
    app.add_routes([
        web.get("/", index), web.get("/api/ping", ping),
        web.post("/api/sessions", create),
        web.get("/s/{id}", page), web.get("/ws/{id}", ws_handler),
    ])
    web.run_app(app, host="0.0.0.0", port=PORT, print=None)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "open"
    if cmd == "serve":
        serve()
    else:
        client_open(sys.argv[2] if len(sys.argv) > 2 else os.getcwd(), sys.argv[3:])
