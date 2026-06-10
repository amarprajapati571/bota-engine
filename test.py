"""
xman.agency login script — macOS variant (fixed v7).
"""

import asyncio
import base64
import datetime
import os
import random
import socket
import subprocess
import sys
import tempfile
import threading
import time
import json
import urllib.error
import urllib.request
import uuid
import builtins

LOG_ONLY_API_AND_SCREENSHOT = True
_real_print = builtins.print


def print(*args, **kwargs):
    if not LOG_ONLY_API_AND_SCREENSHOT:
        return _real_print(*args, **kwargs)
    msg = " ".join(str(a) for a in args)
    keep = (
        "[round-start]" in msg
        or "[overlay-event]" in msg
        or "[upload]" in msg
        or "[screenshot]" in msg
        or "[capture-debug]" in msg
        or "[result-scan]" in msg
        or "[result-ready-skip]" in msg
        or "RESULT HTML READY" in msg
        or "[stopped]" in msg
        or "[health]" in msg
        or "[recovery]" in msg
        or "[audit]" in msg
        or "[betting-started]" in msg
        or "[popup]" in msg
        or "[place-bet]" in msg
        or "[chip]" in msg
        or "[zone]" in msg
        or "[ABORT]" in msg
        or "UNHANDLED" in msg
        or "Traceback" in msg
        or "Error" in msg
        # or "[round-id]" in msg
        or "[round-task]" in msg
        or "[ABORT]" in msg
        or "UNHANDLED" in msg
    )
    if keep:
        return _real_print(*args, **kwargs)

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from patchright.async_api import async_playwright


# ── Config ────────────────────────────────────────────────────────────────────
PROXY_MODE          = "none"
DEFAULT_PROXY_IP    = "45.130.79.79:44444"
DEFAULT_PROXY_USER  = "14a33ce5b8588"
DEFAULT_PROXY_PASS  = "27d58ad674"
PROXY_TXT_PATH      = "proxy.txt"

LOGIN_USERNAME      = "sahanScrap3"
LOGIN_PASSWORD      = "1234"
CLOUDFLARE_WAIT_SEC = 300

GAME_FRAME_URL_HINT = "pragmaticplaylive.net"

SCREENSHOT_TIMER_MIN = 10
SCREENSHOT_TIMER_MAX = 35
POST_ROUNDS_ENDPOINT = "https://bota-parsing.xman.agency/api/roundss"
POST_ROUNDS_TIMEOUT_SEC = 10
_uploaded_round_ids = set()

BLACK_SCREEN_CHECK_INTERVAL = 10
RESULT_ARMED_TIMEOUT_SEC    = 90

ROOM_ID = 110

def _restart_script():
    print("\n[restart] ── RESTARTING SCRIPT ──")
    time.sleep(5)
    try:
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        print(f"[restart] execv failed: {e} — subprocess fallback")
        subprocess.Popen([sys.executable] + sys.argv)
        sys.exit(0)

def _detect_chrome_path():
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
        "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
        "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
        "/snap/bin/chromium", "/usr/bin/chromium", "/usr/bin/chromium-browser",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    env = os.environ.get("CHROME_PATH")
    if env and os.path.exists(env): return env
    for c in candidates:
        if c and os.path.exists(c): return c
    raise RuntimeError("Chrome not found. Set CHROME_PATH.")

CHROME_PATH = _detect_chrome_path()


class AuthRelay:
    def __init__(self, local_port, up_host, up_port, user, password):
        self.local_port = local_port
        self.up_host = up_host
        self.up_port = up_port
        self.auth_hdr = (
            "Proxy-Authorization: Basic "
            f"{base64.b64encode(f'{user}:{password}'.encode()).decode()}\r\n"
        ).encode() if (user and password) else b""
        self._server = self._running = None

    @staticmethod
    def _pipe(src, dst):
        try:
            while True:
                d = src.recv(8192)
                if not d: break
                dst.sendall(d)
        except Exception: pass
        finally:
            for s in (src, dst):
                try: s.shutdown(socket.SHUT_RDWR)
                except: pass
                try: s.close()
                except: pass

    def _handle(self, client):
        client.settimeout(30)
        buf = b""
        try:
            while b"\r\n\r\n" not in buf and len(buf) < 16384:
                c = client.recv(4096)
                if not c: client.close(); return
                buf += c
        except: client.close(); return
        head, _, rest = buf.partition(b"\r\n\r\n")
        lines = head.split(b"\r\n")
        if not lines: client.close(); return
        first = lines[0]
        if self.auth_hdr:
            filt = [l for l in lines[1:] if not l.lower().startswith(b"proxy-authorization:")]
            new_head = first + b"\r\n" + b"\r\n".join(filt) + b"\r\n" + self.auth_hdr + b"\r\n"
        else:
            new_head = head + b"\r\n\r\n"
        try:
            up = socket.create_connection((self.up_host, self.up_port), timeout=30)
            up.sendall(new_head + rest)
        except: client.close(); return
        threading.Thread(target=self._pipe, args=(client, up), daemon=True).start()
        threading.Thread(target=self._pipe, args=(up, client), daemon=True).start()

    def start(self):
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", self.local_port))
        self._server.listen(64)
        self._running = True
        def loop():
            while self._running:
                try: client, _ = self._server.accept()
                except OSError: break
                threading.Thread(target=self._handle, args=(client,), daemon=True).start()
        threading.Thread(target=loop, daemon=True).start()

    def stop(self):
        self._running = False
        try: self._server.close()
        except: pass


def _find_free_port(start=18400):
    for p in range(start, start + 200):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", p)); return p
        except OSError: continue
    raise RuntimeError("No free port")

def launch_chrome_with_cdp(relay_port, cdp_port):
    profile = tempfile.mkdtemp(prefix="xman_chrome_")
    try: open(os.path.join(profile, "First Run"), "w").close()
    except: pass
    cmd = [CHROME_PATH,
           f"--user-data-dir={profile}",
           f"--remote-debugging-port={cdp_port}",
           "--remote-allow-origins=*", "--lang=ko-KR",
           "--no-first-run", "--no-default-browser-check",
           "--disable-default-apps", "--disable-component-update",
           "--disable-sync", "--window-size=1280,900", "--window-position=80,80"]
    if relay_port:
        cmd.insert(5, f"--proxy-server=http=127.0.0.1:{relay_port};https=127.0.0.1:{relay_port}")
    cmd.append("about:blank")
    kw = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if sys.platform == "win32": kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 8
    else: kw["start_new_session"] = True
    return subprocess.Popen(cmd, **kw), profile

def wait_for_cdp_ready(port, timeout=20):
    dl = time.time() + timeout
    while time.time() < dl:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
                r.read(); return True
        except: time.sleep(0.5)
    return False

CF_MARKERS = ("just a moment","잠시만 기다리십시오","attention required","checking your browser")
def _is_cf(t): return any(m in (t or "").lower() for m in CF_MARKERS)

def _pick_datacenter_proxy():
    try: lines = [l.strip() for l in open(PROXY_TXT_PATH) if l.strip()]
    except FileNotFoundError: return None, None, None, None
    if not lines: return None, None, None, None
    e = random.choice(lines)
    if "@" in e:
        creds, hp = e.split("@", 1); u, pw = creds.split(":", 1); h, p = hp.rsplit(":", 1)
        return h, int(p), u, pw
    h, p = e.rsplit(":", 1); return h, int(p), None, None


async def _click_bota(page, ctx):
    bota_selectors = [
        "img[src='/vendors/live-casino/bota.webp']",
        "img[src*='bota.webp']",
        "img[alt='bota']",
        "img[alt*='bota' i]",
        "[class*='bota']",
    ]
    bota_el = None
    for sel in bota_selectors:
        try:
            el = page.locator(sel).first
            await el.wait_for(state="visible", timeout=5000)
            bota_el = el
            print(f"      [bota] found: {sel!r}")
            break
        except Exception:
            continue

    if bota_el is None:
        return page, False

    try:
        async with ctx.expect_page(timeout=10000) as npi:
            await bota_el.click()
        lobby_page = await npi.value
        await lobby_page.wait_for_load_state("domcontentloaded", timeout=30000)
        for _w in range(15):
            try:
                count = await lobby_page.locator(f"#listbox_{ROOM_ID}, a.enter, [onclick*='goRoom']").count()
                if count > 0:
                    break
            except Exception:
                pass
            await asyncio.sleep(1)
        await lobby_page.wait_for_timeout(1000)
        return lobby_page, True
    except Exception as tab_e:
        for _w in range(15):
            try:
                count = await page.locator(f"#listbox_{ROOM_ID}, a.enter, [onclick*='goRoom']").count()
                if count > 0:
                    break
            except Exception:
                pass
            await asyncio.sleep(1)
        await page.wait_for_timeout(1000)
        return page, True


async def _handle_table_select_popup(ctx):
    """
    Find the seam.zisego.com popup page and click the table image.
    The popup HTML is:
      div.layerpopup > div.pop_cont > div.content > table > tr > td >
        a[onclick="choid_view_fun('view')"] > img[src="/images/a.jpg"]
    """
    print(f"      [popup] looking for seam.zisego.com popup page...")

    # Find seam page - wait up to 10s for it to appear
    seam_page = None
    for _w in range(10):
        for pg in ctx.pages:
            if ('zisego' in pg.url or 'seam' in pg.url) and not pg.is_closed():
                seam_page = pg
                break
        if seam_page:
            break
        await asyncio.sleep(1)

    if seam_page is None:
        print(f"      [popup] seam page not found in {[p.url for p in ctx.pages]}")
        return None, False

    print(f"      [popup] found seam page: {seam_page.url[:70]}")

    async def _popup_targets():
        targets = [seam_page]
        try:
            targets.extend([fr for fr in seam_page.frames if fr != seam_page.main_frame])
        except Exception:
            pass
        return targets

    async def _find_table_choice_target(timeout_sec=25):
        deadline = asyncio.get_event_loop().time() + timeout_sec
        probe_js = """
            () => {
                const img = document.querySelector("img[src='/images/a.jpg'], img[src*='/images/a.jpg']");
                const a = document.querySelector("a[onclick*='choid_view_fun']");
                return {
                    found: !!(img || a),
                    hasFn: typeof window.choid_view_fun === 'function',
                    href: a ? a.getAttribute('href') : null,
                    onclick: a ? a.getAttribute('onclick') : null,
                    title: document.title,
                    url: location.href
                };
            }
        """
        while asyncio.get_event_loop().time() < deadline:
            for target in await _popup_targets():
                try:
                    info = await target.evaluate(probe_js)
                    if info.get("found") or info.get("hasFn"):
                        return target, info
                except Exception:
                    pass
            await asyncio.sleep(0.5)
        return None, None

    async def _call_table_choice(target):
        call_js = """
            () => {
                window.__cfRLUnblockHandlers = true;
                try {
                    if (typeof window.choid_view_fun === 'function') {
                        window.choid_view_fun('view');
                        return { ok: true, via: 'choid_view_fun', url: location.href };
                    }
                    const a = document.querySelector("a[onclick*='choid_view_fun']");
                    if (a) {
                        a.dispatchEvent(new MouseEvent('click', {
                            bubbles: true,
                            cancelable: true,
                            view: window
                        }));
                        return { ok: true, via: 'anchor-dispatch', url: location.href };
                    }
                    const img = document.querySelector("img[src='/images/a.jpg'], img[src*='/images/a.jpg']");
                    if (img) {
                        img.click();
                        return { ok: true, via: 'image-click', url: location.href };
                    }
                    return { ok: false, error: 'table choice not found', url: location.href };
                } catch (e) {
                    return { ok: false, error: String(e), url: location.href };
                }
            }
        """
        return await target.evaluate(call_js)

    async def _popup_still_visible():
        visible_js = """
            () => {
                const el = document.querySelector("div.layerpopup, div.pop_cont, a[onclick*='choid_view_fun']");
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return !!(r.width && r.height && s.display !== 'none' &&
                    s.visibility !== 'hidden' && s.opacity !== '0');
            }
        """
        for target in await _popup_targets():
            try:
                if await target.evaluate(visible_js):
                    return True
            except Exception:
                pass
        return False

    async def _best_new_page(pages_before):
        for pg in ctx.pages:
            if id(pg) in pages_before or pg.is_closed():
                continue
            try:
                await pg.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            print(f"      [popup] new page appeared: {pg.url[:70]}")
            return pg
        for pg in ctx.pages:
            if pg.is_closed():
                continue
            try:
                if "gaming-tg.com" in pg.url:
                    print(f"      [popup] gaming page found: {pg.url[:70]}")
                    return pg
            except Exception:
                pass
        return None

    # Wait for the image/function to be ready. The popup can live inside an iframe.
    try:
        pages_before = set(id(p) for p in ctx.pages)
        target, info = await _find_table_choice_target(timeout_sec=25)
        if target is None:
            print(f"      [popup] table choice not found in page/frames")
            return seam_page, True

        print(f"      [popup] table choice ready: {info}")
        call_result = await _call_table_choice(target)
        print(f"      [popup] auto-called choid_view_fun/view: {call_result}")

        for _ in range(30):
            new_page = await _best_new_page(pages_before)
            if new_page:
                await new_page.wait_for_timeout(2000)
                return new_page, True

            if seam_page.is_closed():
                new_page = await _best_new_page(set())
                return (new_page or seam_page), True

            if not await _popup_still_visible():
                print(f"      [popup] popup closed/hidden after auto-call")
                await seam_page.wait_for_timeout(2000)
                return seam_page, True

            await asyncio.sleep(0.5)

    except Exception as e:
        print(f"      [popup] auto-call failed: {e}")

    print(f"      [popup] auto-call done but no navigation detected — proceeding anyway")
    return seam_page, True


async def _click_go_room(page, ctx, room_id=ROOM_ID):
    SCAN_JS = f"""
        () => {{
            const PRIORITY = [
                '#listbox_{room_id} a.enter',
                '#listbox_{room_id} .bpt-info a',
                '#listbox_{room_id} [onclick*="goRoom({room_id})"]',
                'div.game-room a.enter[onclick*="goRoom({room_id})"]',
                'a.enter[onclick*="goRoom({room_id})"]',
                '[onclick*="goRoom({room_id})"]',
            ];
            const tryFind = (doc) => {{
                for (const sel of PRIORITY) {{
                    try {{
                        const el = doc.querySelector(sel);
                        if (!el) continue;
                        const rc = el.getBoundingClientRect();
                        let x, y, w, h;
                        if (rc.width > 0 && rc.height > 0) {{
                            x = rc.x + rc.width/2; y = rc.y + rc.height/2;
                            w = Math.round(rc.width); h = Math.round(rc.height);
                        }} else {{
                            let p = el.parentElement;
                            while (p && p !== doc.body) {{
                                const pr = p.getBoundingClientRect();
                                if (pr.width > 20 && pr.height > 20) {{
                                    x = pr.x + pr.width - 50; y = pr.y + pr.height - 25;
                                    w = Math.round(pr.width); h = Math.round(pr.height); break;
                                }}
                                p = p.parentElement;
                            }}
                            if (x === undefined) {{ x = 0; y = 0; w = 0; h = 0; }}
                        }}
                        return {{ found: true, sel, x, y, w, h,
                            cls: (el.className||'').toString().slice(0,80),
                            onclick: (el.getAttribute('onclick')||'').slice(0,120),
                            hasBox: rc.width > 0 }};
                    }} catch(e) {{}}
                }}
                return null;
            }};
            const mainResult = tryFind(document);
            if (mainResult) return mainResult;
            for (let i = 0; i < window.frames.length; i++) {{
                try {{
                    const r = tryFind(window.frames[i].document);
                    if (r) {{ r.frameIdx = i; return r; }}
                }} catch(e) {{}}
            }}
            return {{ found: false }};
        }}
    """

    print(f"      [goRoom] polling for goRoom({room_id})...")
    found = None

    for attempt in range(20):
        try:
            result = await page.evaluate(SCAN_JS)
            if result.get("found"):
                found = result
                print(f"      [goRoom] found at {attempt}s: onclick={result['onclick']!r}")
                break
        except Exception as e:
            print(f"      [goRoom] scan error {attempt}: {e}")

        for i, frame in enumerate(page.frames):
            if frame == page.main_frame:
                continue
            try:
                result = await frame.evaluate(SCAN_JS)
                if result.get("found"):
                    found = result
                    found["_frame_idx"] = i
                    break
            except Exception:
                pass
        if found:
            break

        await asyncio.sleep(1)

    if not found:
        print(f"      [goRoom] FAILED after 20s")
        return page, False

    if found.get("_frame_idx") is not None:
        frame_idx = found["_frame_idx"]
        if frame_idx < len(page.frames):
            try:
                offset = await page.evaluate(f"""
                    () => {{
                        const iframes = document.querySelectorAll('iframe');
                        const nth = iframes[{frame_idx}];
                        if (nth) {{ const rc = nth.getBoundingClientRect(); return {{x: rc.x, y: rc.y}}; }}
                        return {{x: 0, y: 0}};
                    }}
                """)
                found["x"] += offset["x"]
                found["y"] += offset["y"]
            except Exception:
                pass

    click_x = found["x"]
    click_y = found["y"]
    js_click_sel = found.get("sel", "")

    async def _do_js_click():
        if not js_click_sel:
            return False
        js = f"""
            () => {{
                const SELECTORS = [
                    {repr(js_click_sel)},
                    '#listbox_{ROOM_ID} a.enter',
                    'a.enter[onclick*="goRoom({ROOM_ID})"]',
                    '[onclick*="goRoom({ROOM_ID})"]',
                ];
                const tryDocs = [document];
                for (let i = 0; i < window.frames.length; i++) {{
                    try {{ tryDocs.push(window.frames[i].document); }} catch(e) {{}}
                }}
                for (const doc of tryDocs) {{
                    for (const sel of SELECTORS) {{
                        try {{
                            const el = doc.querySelector(sel);
                            if (el) {{ el.click(); return true; }}
                        }} catch(e) {{}}
                    }}
                }}
                return false;
            }}
        """
        try:
            return await page.evaluate(js)
        except Exception as e:
            print(f"      [goRoom] JS click failed: {e}")
            return False

    # Try JS click — goRoom opens a popup on seam.zisego.com (same ctx, new page)
    print(f"      [goRoom] clicking goRoom({room_id})...")
    js_ok = await _do_js_click()
    if not js_ok:
        try:
            await page.mouse.click(click_x, click_y)
            print(f"      [goRoom] mouse clicked at ({click_x:.0f},{click_y:.0f})")
        except Exception as me:
            print(f"      [goRoom] mouse click failed: {me}")

    # Wait a moment then handle the popup
    await page.wait_for_timeout(2000)
    result_page, ok = await _handle_table_select_popup(ctx)

    if result_page is None:
        result_page = page

    print(f"      [goRoom] result page: {result_page.url[:70]}")
    return result_page, True


# ═════════════════════════════════════════════════════════════════════════════
#  BETTING STARTED DETECTION
# ═════════════════════════════════════════════════════════════════════════════

async def _wait_for_betting_started(game_page, timeout_sec=55):
    deadline = asyncio.get_event_loop().time() + timeout_sec

    script = """
        () => {
            // Method 1: #game_msg visible with 배팅시작 (most reliable)
            const msg = document.getElementById('game_msg');
            if (msg) {
                const s = window.getComputedStyle(msg);
                const txt = (msg.innerText || msg.textContent || '').trim();
                if (s.display !== 'none' && s.visibility !== 'hidden' && txt.includes('배팅시작')) {
                    return { found: true, via: 'game_msg' };
                }
            }

            // Method 2: #btn_submit enabled (reliable — disabled during dealing/result)
            const btn = document.getElementById('btn_submit');
            if (btn && !btn.disabled) {
                return { found: true, via: 'btn_submit_enabled' };
            }

            // Method 3: #container timer visible AND #game_msg is visible (not hidden)
            // Guard: game_msg must exist and not be display:none to avoid false positives
            const gameMsgEl = document.getElementById('game_msg');
            const gameMsgVisible = gameMsgEl &&
                window.getComputedStyle(gameMsgEl).display !== 'none' &&
                window.getComputedStyle(gameMsgEl).visibility !== 'hidden';
            const container = document.getElementById('container');
            if (container && gameMsgVisible) {
                const s = window.getComputedStyle(container);
                if (s.display !== 'none' && s.visibility !== 'hidden') {
                    const lines = (container.innerText || container.textContent || '')
                        .split('\\n').map(l => l.trim()).filter(l => /^\\d+$/.test(l));
                    if (lines.length > 0) {
                        const v = parseInt(lines[0], 10);
                        if (v >= 1 && v <= 60) {
                            return { found: true, via: 'container_timer', value: v };
                        }
                    }
                }
            }

            // Method 4: #pp_bet visible AND #btn_submit is enabled
            // Both must be true to avoid false positives during dealing phase
            const pp = document.getElementById('pp_bet');
            const submitBtn = document.getElementById('btn_submit');
            if (pp && submitBtn && !submitBtn.disabled) {
                const r = pp.getBoundingClientRect();
                const s = window.getComputedStyle(pp);
                if (r.width > 0 && r.height > 0 && s.display !== 'none') {
                    return { found: true, via: 'pp_bet_and_submit_enabled' };
                }
            }

            return { found: false };
        }
    """

    while asyncio.get_event_loop().time() < deadline:
        if hasattr(game_page, 'frames'):
            targets = [game_page] + list(game_page.frames)
        else:
            targets = [game_page]
        for target in targets:
            try:
                result = await target.evaluate(script)
                if result.get('found'):
                    via = result.get('via')
                    # print(f"      [betting-started] DETECTED via={via} — waiting 5s...")
                    # await asyncio.sleep(5)
                    print(f"      [betting-started] DETECTED via={via}")
                    return True
            except Exception:
                pass
        await asyncio.sleep(0.15)

    print(f"      [betting-started] timeout after {timeout_sec}s")
    return False

# ═════════════════════════════════════════════════════════════════════════════
#  DEEP DOM AUDIT
# ═════════════════════════════════════════════════════════════════════════════

async def _deep_dom_audit(game_page, label="audit"):
    ts = datetime.datetime.now().strftime("%H%M%S")
    out_path = f"screenshots/dom_audit_{label}_{ts}.json"
    os.makedirs("screenshots", exist_ok=True)

    script = """
    () => {
        const results = {
            url: location.href, title: document.title,
            viewport: { w: window.innerWidth, h: window.innerHeight },
            resultElements: [], cardElements: [], images: [],
            scoreTexts: [], badgeElements: [], domTree: []
        };
        const isVisible = (el) => {
            const r = el.getBoundingClientRect();
            if (!r.width || !r.height) return false;
            const s = window.getComputedStyle(el);
            return s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
        };
        const elInfo = (el, extra) => {
            const r = el.getBoundingClientRect();
            const txt = (el.innerText || el.textContent || '').trim().slice(0, 120);
            return { tag: el.tagName, id: el.id || '',
                cls: (el.className || '').toString().slice(0, 120), txt,
                visible: isVisible(el),
                rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
                src: el.getAttribute('src') || '', children: el.children.length, ...extra };
        };
        for (const el of document.querySelectorAll('[class*="result"],[id*="result"]'))
            results.resultElements.push(elInfo(el));
        for (const el of document.querySelectorAll('[class*="card"],[id*="card"]'))
            results.cardElements.push(elInfo(el));
        for (const el of document.querySelectorAll('img')) {
            const src = el.getAttribute('src') || el.src || '';
            if (src) results.images.push(elInfo(el, { fullSrc: src }));
        }
        for (const el of document.querySelectorAll('*')) {
            if (el.children.length > 0) continue;
            const txt = (el.innerText || el.textContent || '').trim();
            if (!/^[0-9]$/.test(txt) || !isVisible(el)) continue;
            results.scoreTexts.push(elInfo(el));
        }
        for (const el of document.querySelectorAll('[class*="badge"],[id*="badge"],[class*="round"],[id*="round"]'))
            results.badgeElements.push(elInfo(el));
        const walk = (el, depth) => {
            if (depth > 8) return;
            const r = el.getBoundingClientRect();
            results.domTree.push({ depth, tag: el.tagName, id: el.id || '',
                cls: (el.className || '').toString().slice(0, 80),
                visible: !!(r.width && r.height),
                rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) } });
            for (const child of el.children) walk(child, depth + 1);
        };
        walk(document.body, 0);
        return results;
    }
    """

    all_audits = []
    targets = [("page", game_page)] + [
        (f"frame[{i}]:{f.url[:60]}", f) for i, f in enumerate(game_page.frames)
    ]
    for label_ctx, target in targets:
        try:
            data = await target.evaluate(script)
            data["context"] = label_ctx
            all_audits.append(data)
            print(f"\n{'='*60}")
            print(f"[audit] CTX: {label_ctx} | URL: {data['url']}")
            print(f"[audit] resultElements ({len(data['resultElements'])}):")
            for e in data['resultElements'][:10]:
                mark = "✅" if e['visible'] else "❌"
                print(f"  {mark} tag={e['tag']} cls={e['cls']!r} txt={e['txt']!r}")
            print(f"[audit] cardElements visible:")
            for e in data['cardElements'][:15]:
                if e['visible']:
                    print(f"  ✅ tag={e['tag']} cls={e['cls']!r} src={e['src'][:60]!r}")
            print(f"[audit] images visible:")
            for e in data['images'][:20]:
                if e['visible']:
                    print(f"  ✅ src={e['fullSrc'][:80]!r} rect={e['rect']}")
        except Exception as e:
            print(f"[audit] ERROR on {label_ctx}: {e}")
            all_audits.append({"context": label_ctx, "error": str(e)})

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(all_audits, f, indent=2, ensure_ascii=False)
        print(f"\n[audit] saved: {out_path}")
    except Exception as e:
        print(f"[audit] failed to save: {e}")

    return all_audits


# ═════════════════════════════════════════════════════════════════════════════
#  SCREENSHOT / ROUND ID
# ═════════════════════════════════════════════════════════════════════════════

async def _read_betting_timer(game_page):
    # Try your game's actual timer element first
    for sel in ["#container", ".countdown_status", "[id*='countdown']"]:
        try:
            el = game_page.locator(sel).first
            if await el.count() == 0:
                continue
            txt = (await el.inner_text(timeout=500)).strip()
            # Clean up — get just the number
            lines = [l.strip() for l in txt.splitlines() if l.strip().isdigit()]
            if lines:
                v = int(lines[0])
                if 1 <= v <= 60:
                    return True, v, None
        except Exception:
            pass
    
    # Fallback to original .badge-number
    try:
        el = game_page.locator(".badge-number").first
        if await el.count() == 0:
            return False, None, None
        txt = (await el.inner_text(timeout=500)).strip()
        if txt.startswith("#"):
            return False, None, txt
        v = int(txt)
        if 1 <= v <= 60:
            return True, v, None
    except Exception:
        pass
    
    return False, None, None


# async def _read_round_id(game_page):
#     # Primary: #game_cnt element (most reliable for this game)
#     try:
#         info = await game_page.evaluate("""
#             () => {
#                 const el = document.getElementById('game_cnt');
#                 if (el) {
#                     const txt = (el.innerText || el.textContent || '').trim();
#                     if (txt && /^\d+$/.test(txt)) return txt;
#                 }
#                 return null;
#             }
#         """)
#         if info:
#             return info
#     except Exception:
#         pass

#     # Fallback: .round-badge
#     for sel in [".round-badge .badge-number", ".round-badge [class*='badge-number']"]:
#         try:
#             el = game_page.locator(sel).first
#             if await el.count() == 0:
#                 continue
#             txt = (await el.inner_text(timeout=500)).strip()
#             if txt.startswith("#"):
#                 return txt
#         except Exception:
#             pass

#     _, _, badge_round_id = await _read_betting_timer(game_page)
#     return badge_round_id

# async def _read_round_id(game_page):
#     # Primary: #game_cnt element
#     try:
#         info = await game_page.evaluate("""
#             () => {
#                 const el = document.getElementById('game_cnt');
#                 if (el) {
#                     const txt = (el.innerText || el.textContent || '').trim();
#                     if (txt && /^\d+$/.test(txt)) return txt;
#                 }
#                 return null;
#             }
#         """)
#         if info:
#             print(f"      [round-id] game_cnt={info!r}")
#             return info
#         else:
#             print(f"      [round-id] game_cnt not found in {getattr(game_page, 'url', '?')[:50]}")
#     except Exception as e:
#         print(f"      [round-id] error: {e}")

#     # Fallback
#     for sel in [".round-badge .badge-number", ".round-badge [class*='badge-number']"]:
#         try:
#             el = game_page.locator(sel).first
#             if await el.count() == 0:
#                 continue
#             txt = (await el.inner_text(timeout=500)).strip()
#             if txt.startswith("#"):
#                 return txt
#         except Exception:
#             pass

#     _, _, badge_round_id = await _read_betting_timer(game_page)
#     return badge_round_id

async def _read_round_id(game_page):
    try:
        info = await game_page.evaluate("""
            () => {
                const el = document.getElementById('game_cnt');
                if (el) {
                    const txt = (el.innerText || el.textContent || '').trim();
                    if (txt && /^\d+$/.test(txt)) return txt;
                }
                return null;
            }
        """)
        if info:
            return info
    except Exception:
        pass

    for sel in [".round-badge .badge-number", ".round-badge [class*='badge-number']"]:
        try:
            el = game_page.locator(sel).first
            if await el.count() == 0:
                continue
            txt = (await el.inner_text(timeout=500)).strip()
            if txt.startswith("#"):
                return txt
        except Exception:
            pass

    _, _, badge_round_id = await _read_betting_timer(game_page)
    return badge_round_id

def _previous_round_id(round_id):
    if not round_id:
        return round_id
    txt = str(round_id).strip()
    num_txt = txt[1:] if txt.startswith("#") else txt
    if not num_txt.isdigit():
        return round_id
    return str(max(0, int(num_txt) - 1))


def _strip_round_id_hash(round_id):
    if round_id is None:
        return None
    txt = str(round_id).strip()
    return txt[1:] if txt.startswith("#") else txt


async def _take_screenshot(game_page, round_count, timer_val, round_id=None, result_data=None):
    os.makedirs("screenshots", exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    timer_label = f"{timer_val:02d}" if isinstance(timer_val, int) else str(timer_val)
    fname = f"screenshots/round{round_count:04d}_t{timer_label}_{ts}.png"
    json_path = "screenshots/rounds.json"

    try:
        await game_page.screenshot(path=fname)
        print(f"      [screenshot] saved: {fname}")
    except Exception as e:
        print(f"      [screenshot] failed: {e}")
        return

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    upload_round_id = _previous_round_id(round_id) if round_id else str(round_count)
    entry = {
        "round_count": round_count, "round_id": upload_round_id,
        "source_round_id": round_id, "timer_val": timer_val,
        "timestamp": ts, "image_path": fname
    }
    if result_data:
        entry["result_data"] = result_data
    data.append(entry)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"      [screenshot] JSON updated: {json_path}")
    print(f"      [screenshot] upload round_id={upload_round_id!r} source_round_id={round_id!r}")

    # if str(timer_val) == "betting_started":
    #     if upload_round_id in _uploaded_round_ids:
    #         print(f"      [upload] SKIPPED (duplicate)")
    #     else:
    #         _uploaded_round_ids.add(upload_round_id)
    #         await _post_round_image(fname, upload_round_id)
    # else:
    #     print(f"      [upload] SKIPPED timer_val={timer_val!r}")

    # if str(timer_val) == "betting_started":
    #     # Dedup by source_round_id (game_cnt), not upload_round_id
    #     dedup_key = str(round_id) if round_id else str(upload_round_id)
    #     if dedup_key in _uploaded_round_ids:
    #         print(f"      [upload] SKIPPED (duplicate dedup_key={dedup_key!r})")
    #     else:
    #         _uploaded_round_ids.add(dedup_key)
    #         await _post_round_image(fname, upload_round_id)
    # else:
    #     print(f"      [upload] SKIPPED timer_val={timer_val!r}")


    if str(timer_val) == "betting_started":
        dedup_key = str(upload_round_id)
        if dedup_key in _uploaded_round_ids:
            print(f"      [upload] SKIPPED (duplicate dedup_key={dedup_key!r})")
        else:
            _uploaded_round_ids.add(dedup_key)
            await _post_round_image(fname, upload_round_id)
    else:
        print(f"      [upload] SKIPPED timer_val={timer_val!r}")


def _post_round_image_sync(image_path, round_id):
    boundary = f"----round-upload-{uuid.uuid4().hex}"
    filename = os.path.basename(image_path)
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    body = b"".join([
        f"--{boundary}\r\n".encode("utf-8"),
        b'Content-Disposition: form-data; name="round_id"\r\n\r\n',
        str(round_id).encode("utf-8"), b"\r\n",
        f"--{boundary}\r\n".encode("utf-8"),
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'.encode("utf-8"),
        b"Content-Type: image/png\r\n\r\n",
        image_bytes, b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ])
    req = urllib.request.Request(
        POST_ROUNDS_ENDPOINT, data=body, method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json", "User-Agent": "bota4-bot/1.0",
            "Content-Length": str(len(body)),
        },
    )
    with urllib.request.urlopen(req, timeout=POST_ROUNDS_TIMEOUT_SEC) as resp:
        return resp.status, resp.read(1000).decode("utf-8", errors="replace")


async def _post_round_image(image_path, round_id):
    try:
        size = os.path.getsize(image_path)
        print(f"      [upload] CALLING {POST_ROUNDS_ENDPOINT} round_id={round_id!r} size={size}")
        status, preview = await asyncio.to_thread(_post_round_image_sync, image_path, round_id)
        print(f"      [upload] POST status={status} body={preview[:500]!r}")
    except urllib.error.HTTPError as e:
        body = e.read(1000).decode("utf-8", errors="replace")
        print(f"      [upload] POST failed status={e.code} reason={e.reason!r} body={body!r}")
    except urllib.error.URLError as e:
        print(f"      [upload] POST failed url_error={e}")
    except Exception as e:
        print(f"      [upload] POST failed error={e}")


# ═════════════════════════════════════════════════════════════════════════════
#  GAME STATE
# ═════════════════════════════════════════════════════════════════════════════

async def _read_result_cards(game_page):
    script = """
        () => {
            // Check for this game's result structure
            const pScore = document.getElementById('p_score');
            const bScore = document.getElementById('b_score');
            const resultDiv = document.querySelector('.item_result');

            if (!resultDiv || !pScore || !bScore) {
                return { valid: false, captureReady: false, reason: 'no-result-root',
                    rootCount: 0, playerBoxCount: 0, bankerBoxCount: 0, openCardCount: 0,
                    title: document.title || '', url: location.href };
            }

            const r = resultDiv.getBoundingClientRect();
            const rootVisible = !!(r.width && r.height &&
                window.getComputedStyle(resultDiv).display !== 'none' &&
                window.getComputedStyle(resultDiv).visibility !== 'hidden');

            const ps = parseInt((pScore.innerText || pScore.textContent || '').trim(), 10);
            const bs = parseInt((bScore.innerText || bScore.textContent || '').trim(), 10);
            const scoresReady = !isNaN(ps) && !isNaN(bs);

            // Read cards from CSS class names like d_7, c_1, s_9, h_K etc.
            const parseCardFromClass = (el) => {
                if (!el) return null;
                const cls = (el.className || '').toString();
                const m = cls.match(/\\b([cdsh])_([0-9AJQK]+)\\b/i);
                if (!m || m[2] === '0') return null;
                return { code: `${m[2]}${m[1].toUpperCase()}`, suit: m[1], rank: m[2] };
            };

            const p1 = parseCardFromClass(document.getElementById('popCardAreaP1'));
            const p2 = parseCardFromClass(document.getElementById('popCardAreaP2'));
            const p3 = parseCardFromClass(document.getElementById('popCardAreaP3'));
            const b1 = parseCardFromClass(document.getElementById('popCardAreaB1'));
            const b2 = parseCardFromClass(document.getElementById('popCardAreaB2'));
            const b3 = parseCardFromClass(document.getElementById('popCardAreaB3'));

            const playerCards = [p1, p2, p3].filter(Boolean);
            const bankerCards = [b1, b2, b3].filter(Boolean);
            const enoughCards = playerCards.length >= 2 && bankerCards.length >= 2;
            const hasCards = enoughCards && scoresReady;

            return {
                valid: rootVisible && hasCards,
                captureReady: hasCards,
                reason: !hasCards ? (!enoughCards ? 'waiting-cards' : 'waiting-scores') : 'ok',
                rootVisible,
                playerScore: scoresReady ? ps : null,
                bankerScore: scoresReady ? bs : null,
                playerCards: playerCards.map(c => ({ code: c.code, src: c.code })),
                bankerCards: bankerCards.map(c => ({ code: c.code, src: c.code })),
                signature: JSON.stringify({
                    p: playerCards.map(c => c.code),
                    b: bankerCards.map(c => c.code),
                    ps, bs
                }),
                rootCount: 1,
                playerBoxCount: playerCards.length,
                bankerBoxCount: bankerCards.length,
                openCardCount: playerCards.length + bankerCards.length,
                title: document.title || '', url: location.href
            };
        }
    """
    probes = []
    targets = [("page", game_page)]
    for i, frame in enumerate(getattr(game_page, "frames", []) or []):
        targets.append((f"frame[{i}]", frame))

    for label, target in targets:
        try:
            data = await target.evaluate(script)
            data["context"] = label
            probes.append(data)
            if data.get("captureReady"):
                return data
        except Exception as e:
            probes.append({"valid": False, "reason": f"eval-error: {e}", "context": label})

    for data in probes:
        if data.get("rootCount") or data.get("openCardCount"):
            data["probes"] = probes
            return data

    return probes[0] if probes else {"valid": False, "reason": "no-probes"}


async def _read_wrapper_state(game_page):
    try:
        r = await game_page.evaluate("""
            () => {
                let timerValue = null;

                // Method 0: Your game's betting signal via #game_msg
                const gameMsg = document.getElementById('game_msg');
                if (gameMsg) {
                    const msgTxt = (gameMsg.innerText || gameMsg.textContent || '').trim();
                    const msgStyle = window.getComputedStyle(gameMsg);
                    if (msgStyle.display !== 'none' && msgStyle.visibility !== 'hidden'
                            && msgTxt.includes('배팅시작')) {
                        timerValue = 30;
                    }
                }

                // Method 1: #container timer (TIME 21 display)
                if (timerValue === null) {
                    const containerEl = document.getElementById('container');
                    if (containerEl) {
                        const lines = (containerEl.innerText || containerEl.textContent || '')
                            .split('\\n').map(l => l.trim()).filter(l => /^\\d+$/.test(l));
                        if (lines.length > 0) {
                            const v = parseInt(lines[0], 10);
                            if (v >= 1 && v <= 60) timerValue = v;
                        }
                    }
                }

                // Method 2: .badge-number
                if (timerValue === null) {
                    const badgeEl = document.querySelector('.badge-number');
                    if (badgeEl) {
                        const txt = (badgeEl.innerText || badgeEl.textContent || '').trim();
                        const v = parseInt(txt, 10);
                        if (!isNaN(v) && v >= 1 && v <= 60) timerValue = v;
                    }
                }

                // Method 3: common timer selectors
                if (timerValue === null) {
                    const timerSelectors = ['.countdown', '.timer', '.bet-timer',
                        '[class*="countdown"]', '[class*="timer"]', '[class*="count-down"]'];
                    for (const sel of timerSelectors) {
                        const el = document.querySelector(sel);
                        if (!el) continue;
                        const txt = (el.innerText || el.textContent || '').trim();
                        const v = parseInt(txt, 10);
                        if (!isNaN(v) && v >= 1 && v <= 60) { timerValue = v; break; }
                    }
                }

                // Method 4: scan all visible leaf elements for a number
                if (timerValue === null) {
                    for (const el of document.querySelectorAll('*')) {
                        if (el.children.length > 0) continue;
                        const txt = (el.innerText || el.textContent || '').trim();
                        if (!/^[0-9]{1,2}$/.test(txt)) continue;
                        const v = parseInt(txt, 10);
                        if (v < 1 || v > 60) continue;
                        const rc = el.getBoundingClientRect();
                        if (rc.width === 0) continue;
                        const fs = parseFloat(window.getComputedStyle(el).fontSize || 0);
                        if (fs >= 14) { timerValue = v; break; }
                    }
                }

                const isOpen = timerValue !== null;

                // Result / winner detection
                const WIN_KEYS = ['Banker', 'Player', 'Tie', '뱅커', '플레이어', '무승부'];
                let result = null, showingResult = false;
                const resultRoot = document.querySelector('.bkr-game-result-bottom');
                if (resultRoot) {
                    const rc = resultRoot.getBoundingClientRect();
                    showingResult = !!(rc.width && rc.height);
                }
                for (const el of document.querySelectorAll('*')) {
                    if (el.children.length > 0) continue;
                    const t = (el.innerText || el.textContent || '').trim();
                    if (!WIN_KEYS.includes(t)) continue;
                    const rc = el.getBoundingClientRect();
                    if (rc.width && rc.height) { result = t; showingResult = true; break; }
                }

                const roadCount = document.querySelectorAll(
                    '[class*="road"] circle, [class*="bead"], [class*="road-item"]'
                ).length;

                return {
                    open: isOpen, cd: isOpen ? String(timerValue) : null, src: 'wrapper',
                    showingResult, result, pScore: null, bScore: null, roadCount,
                    vW: window.innerWidth, vH: window.innerHeight
                };
            }
        """)
        return bool(r.get('open')), r.get('cd'), r
    except Exception as e:
        return False, None, {'error': str(e)}

async def _read_balance(frame):
    for sel in ["[data-testid='balance']","[data-testid*='balance']",
                "[class*='balance']","[class*='Balance']"]:
        try:
            t = (await frame.locator(sel).first.inner_text(timeout=1000)).strip()
            if t:
                lines = [l.strip() for l in t.splitlines() if l.strip()]
                return lines[-1] if lines else t
        except: continue
    return "n/a"

async def _read_chip_value(frame, testid):
    try: return (await frame.locator(f"[data-testid='{testid}']").first.inner_text(timeout=2000)).strip()
    except: return None


# ═════════════════════════════════════════════════════════════════════════════
#  IFRAME-AWARE CLICKING
# ═════════════════════════════════════════════════════════════════════════════

async def _get_iframe_offset(game_frame, top_page):
    parent = game_frame.parent_frame
    if parent is None: return 0.0, 0.0
    try:
        r = await asyncio.wait_for(parent.evaluate("""
            (url) => {
                // Try matching by src URL
                for (const f of document.querySelectorAll('iframe,frame')) {
                    const src = f.src || '';
                    if (src && (url.includes(src.split('?')[0].split('/').pop()) ||
                                src.includes('view') || src.includes('list2'))) {
                        const rc = f.getBoundingClientRect();
                        if (rc.width > 200 && rc.height > 200)
                            return {x: rc.x, y: rc.y, w: rc.width, h: rc.height};
                    }
                }
                // Fallback: largest iframe
                let best = null, bestArea = 0;
                for (const f of document.querySelectorAll('iframe,frame')) {
                    const rc = f.getBoundingClientRect();
                    const area = rc.width * rc.height;
                    if (area > bestArea) { best = rc; bestArea = area; }
                }
                if (best && best.width > 200)
                    return {x: best.x, y: best.y, w: best.width, h: best.height};
                return {x:0, y:0, w:0, h:0};
            }
        """, game_frame.url), timeout=3.0)
        return float(r['x']), float(r['y'])
    except Exception as e:
        print(f"      [iframe-offset] error: {e}")
        return 0.0, 0.0

async def _iframe_click(top_page, game_frame, ix, iy, label):
    ox, oy = await _get_iframe_offset(game_frame, top_page)
    px, py = ix + ox, iy + oy
    print(f"      [click] {label}: page=({px:.0f},{py:.0f})")
    try:
        await top_page.mouse.click(px, py)
        return True
    except Exception as e:
        print(f"      [click] FAILED {label}: {e}")
        return False


async def _find_bet_zone(game_frame, korean, english, min_w=80, min_h=50):
    ID_MAP = {
        '플레이어': 'leftBet', 'Player': 'leftBet',
        '뱅커': 'rightBet', 'Banker': 'rightBet',
        '무승부': 'centerTopBet', 'Tie': 'centerTopBet',
    }
    zone_id = ID_MAP.get(korean) or ID_MAP.get(english)
    try:
        r = await game_frame.evaluate(f"""
            () => {{
                let el = null;
                const stableId = {repr(zone_id)};
                if (stableId) {{
                    el = document.getElementById(stableId);
                    if (el) {{
                        const rc = el.getBoundingClientRect();
                        if (rc.width < 40 || rc.height < 20) {{
                            let p = el.parentElement;
                            while (p && p !== document.body) {{
                                const pr = p.getBoundingClientRect();
                                if (pr.width >= {min_w} && pr.height >= {min_h}) {{ el = p; break; }}
                                p = p.parentElement;
                            }}
                        }}
                    }}
                }}
                if (!el) {{
                    const tgts = ['{korean}', '{english}'];
                    let best = null;
                    for (const e of document.querySelectorAll('*')) {{
                        const t = (e.innerText||e.textContent||'').trim();
                        if (!tgts.some(k=>t===k || t.startsWith(k+'\\n') || t.startsWith(k+' '))) continue;
                        const rc = e.getBoundingClientRect();
                        if (rc.width < {min_w} || rc.height < {min_h}) continue;
                        const area = rc.width * rc.height;
                        if (!best || area > best.area) best = {{ el: e, area }};
                    }}
                    if (best) el = best.el;
                }}
                if (!el) return null;
                const rc = el.getBoundingClientRect();
                if (!rc.width || !rc.height) return null;
                return {{ x: rc.x + rc.width/2, y: rc.y + rc.height/2,
                          w: Math.round(rc.width), h: Math.round(rc.height),
                          id: el.id || '', cls: (el.className||'').toString().slice(0, 80) }};
            }}
        """)
        if r and r.get('w', 0) > 0:
            return r['x'], r['y']
    except Exception as e:
        print(f"      [zone] error '{korean}': {e}")
    return None, None


async def _click_by_id(top_page, game_frame, elem_id, label):
    try:
        r = await game_frame.evaluate(f"""
            () => {{
                const el = document.getElementById('{elem_id}');
                if (!el) return null;
                const rc = el.getBoundingClientRect();
                if (!rc.width || !rc.height) return null;
                return {{ x: rc.x + rc.width/2, y: rc.y + rc.height/2,
                          w: Math.round(rc.width), h: Math.round(rc.height) }};
            }}
        """)
        if r and r.get('w', 0) > 0:
            return await _iframe_click(top_page, game_frame, r['x'], r['y'], label)
        return False
    except Exception as e:
        print(f"      [click_id] error {elem_id}: {e}")
        return False


async def _find_chip_on_wrapper(game_page):
    try:
        el = game_page.locator("#C_1000").first
        await el.wait_for(state="visible", timeout=3000)
        box = await el.bounding_box()
        if box:
            x = box['x'] + box['width'] / 2
            y = box['y'] + box['height'] / 2
            print(f"      [chip] C_1000 at ({x:.0f},{y:.0f})")
            return x, y
    except Exception as e:
        print(f"      [chip] C_1000 not found on {getattr(game_page, 'url', '?')[:50]}: {e}")
    return None, None

async def _click_banker_on_wrapper(top_page, game_page, game_frame=None):
    # Build target list — prioritize game_frame if provided
    if game_frame is not None:
        targets = [game_frame, game_page] + [f for f in game_page.frames if f != game_frame]
    else:
        targets = [game_page] + list(game_page.frames)

    for target in targets:
        # Step 1: click #pp_bet using page mouse with iframe offset
        try:
            pp_info = await target.evaluate("""
                () => {
                    const el = document.getElementById('pp_bet');
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    if (!r.width || !r.height) return null;
                    return { x: r.x + r.width/2, y: r.y + r.height/2, w: r.width, h: r.height };
                }
            """)
            if not pp_info:
                continue

            # Get iframe offset if target is a frame
            if hasattr(target, 'parent_frame') and target.parent_frame is not None:
                ox, oy = await _get_iframe_offset(target, top_page)
            else:
                ox, oy = 0.0, 0.0

            px = pp_info['x'] + ox
            py = pp_info['y'] + oy
            await top_page.mouse.click(px, py)
            print(f"      [zone] #pp_bet clicked at ({px:.0f},{py:.0f}) offset=({ox:.0f},{oy:.0f})")

        except Exception as e:
            print(f"      [zone] #pp_bet click error: {e}")
            continue

        await asyncio.sleep(0.5)

        # Step 2: find and click confirm button via page mouse with iframe offset
        try:
            confirm_info = await target.evaluate("""
                () => {
                    // Try #btn_submit first
                    let el = document.getElementById('btn_submit');
                    if (el && !el.disabled) {
                        const r = el.getBoundingClientRect();
                        if (r.width && r.height)
                            return { x: r.x + r.width/2, y: r.y + r.height/2, via: 'btn_submit' };
                    }

                    // Text match 배팅하기 / 베팅하기
                    for (const e of document.querySelectorAll('*')) {
                        const t = (e.innerText || e.textContent || '').trim();
                        if (t !== '배팅하기' && t !== '베팅하기') continue;
                        const r = e.getBoundingClientRect();
                        if (r.width && r.height)
                            return { x: r.x + r.width/2, y: r.y + r.height/2, via: 'text_배팅하기' };
                    }

                    // onclick match
                    for (const e of document.querySelectorAll('[onclick]')) {
                        const oc = e.getAttribute('onclick') || '';
                        if (!oc.includes('bet') && !oc.includes('Bet') && !oc.includes('submit')) continue;
                        const r = e.getBoundingClientRect();
                        if (r.width && r.height)
                            return { x: r.x + r.width/2, y: r.y + r.height/2,
                                     via: 'onclick', onclick: oc.slice(0, 60) };
                    }

                    return null;
                }
            """)

            if confirm_info:
                if hasattr(target, 'parent_frame') and target.parent_frame is not None:
                    ox, oy = await _get_iframe_offset(target, top_page)
                else:
                    ox, oy = 0.0, 0.0
                px = confirm_info['x'] + ox
                py = confirm_info['y'] + oy
                await top_page.mouse.click(px, py)
                print(f"      [zone] confirm clicked via={confirm_info.get('via')} at ({px:.0f},{py:.0f}) ✓")
                return True
            else:
                print(f"      [zone] confirm button not found in {getattr(target, 'url', '?')[:50]}")

        except Exception as e:
            print(f"      [zone] confirm click failed: {e}")

    print(f"      [zone] PP bet not placed on any frame")
    return False

async def _place_bet(top_page, game_frame, poll_frame, bet_open_at, bet_cd,
                     round_id=None, iframe_ox=0.0, iframe_oy=0.0):
    loop = asyncio.get_event_loop()
    def _ts(): return f"+{loop.time()-bet_open_at:.2f}s"

    try:
        print(f"      [{_ts()}] [place-bet] START timer={bet_cd}s iframe_offset=({iframe_ox:.0f},{iframe_oy:.0f})")

        # ── Round start API ──────────────────────────────────────────────────
        try:
            try: timer_value = int(bet_cd)
            except (TypeError, ValueError): timer_value = bet_cd
            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
            payload = json.dumps({
                "event": "place_bet_start",
                "round_id": _strip_round_id_hash(round_id),
                "round_count": None, "started_at": timestamp,
                "timer": timer_value, "status": "BETTING", "timestamp_ms": timestamp,
            }).encode("utf-8")
            print(f"      [{_ts()}] [round-start] CALLING https://bota-parsing.xman.agency/api/round-startt payload={payload.decode('utf-8')}")
            req = urllib.request.Request(
                "https://bota-parsing.xman.agency/api/round-startt",
                data=payload, method="POST",
                headers={"Content-Type": "application/json", "Accept": "application/json",
                         "User-Agent": "bota4-bot/1.0", "Content-Length": str(len(payload))},
            )
            status, body = await asyncio.to_thread(
                lambda: (lambda r: (r.status, r.read(200).decode("utf-8", errors="replace")))(
                    urllib.request.urlopen(req, timeout=5)
                )
            )
            print(f"      [{_ts()}] [round-start] POST status={status} {body[:80]!r}")
        except Exception as e:
            print(f"      [{_ts()}] [round-start] failed: {e}")

        # ── Chip click ───────────────────────────────────────────────────────
        print(f"      [{_ts()}] [place-bet] looking for chip C_1000...")
        chip_x, chip_y = None, None
        try:
            chip_info = await asyncio.wait_for(game_frame.evaluate("""
                () => {
                    const el = document.getElementById('C_1000');
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    if (!r.width || !r.height) return null;
                    return { x: r.x + r.width/2, y: r.y + r.height/2 };
                }
            """), timeout=3.0)
            if chip_info:
                chip_x = chip_info['x'] + iframe_ox
                chip_y = chip_info['y'] + iframe_oy
                print(f"      [{_ts()}] [chip] found at frame=({chip_info['x']:.0f},{chip_info['y']:.0f}) page=({chip_x:.0f},{chip_y:.0f})")
        except Exception as e:
            print(f"      [{_ts()}] [chip] game_frame lookup failed: {e}")

        # Fallback: scan all frames
        if chip_x is None:
            print(f"      [{_ts()}] [chip] trying fallback frames...")
            for f in top_page.frames:
                try:
                    chip_info = await asyncio.wait_for(f.evaluate("""
                        () => {
                            const el = document.getElementById('C_1000');
                            if (!el) return null;
                            const r = el.getBoundingClientRect();
                            if (!r.width || !r.height) return null;
                            return { x: r.x + r.width/2, y: r.y + r.height/2 };
                        }
                    """), timeout=2.0)
                    if chip_info:
                        chip_x = chip_info['x'] + iframe_ox
                        chip_y = chip_info['y'] + iframe_oy
                        print(f"      [{_ts()}] [chip] fallback found at ({chip_x:.0f},{chip_y:.0f}) frame={f.url[:40]}")
                        break
                except Exception:
                    continue

        if chip_x is None:
            print(f"      [{_ts()}] [ABORT] chip not found anywhere")
            return False

        try:
            await top_page.mouse.click(chip_x, chip_y)
            print(f"      [{_ts()}] [chip] clicked ✓")
        except Exception as e:
            print(f"      [{_ts()}] [chip] click failed: {e}")
            return False

        await asyncio.sleep(0.5)

        still_open, rem_cd, _ = await _read_wrapper_state(game_frame)
        if not still_open:
            print(f"      [{_ts()}] [ABORT] betting closed after chip click")
            return False
        print(f"      [{_ts()}] [place-bet] betting still open cd={rem_cd}s")
        await asyncio.sleep(0.15)

        # ── PP bet + confirm ─────────────────────────────────────────────────
        print(f"      [{_ts()}] [place-bet] clicking pp_bet + confirm...")
        try:
            bet_info = await asyncio.wait_for(game_frame.evaluate("""
                () => {
                    const pp = document.getElementById('pp_bet');
                    if (!pp) return { pp: null, confirm: null };
                    const pr = pp.getBoundingClientRect();

                    let confirm_el = document.getElementById('btn_submit');
                    if (!confirm_el || confirm_el.disabled) {
                        for (const e of document.querySelectorAll('*')) {
                            const t = (e.innerText || e.textContent || '').trim();
                            if (t !== '배팅하기' && t !== '베팅하기') continue;
                            const r = e.getBoundingClientRect();
                            if (r.width && r.height) { confirm_el = e; break; }
                        }
                    }
                    const cr = confirm_el ? confirm_el.getBoundingClientRect() : null;
                    return {
                        pp: pr.width ? { x: pr.x + pr.width/2, y: pr.y + pr.height/2 } : null,
                        confirm: (cr && cr.width) ? { x: cr.x + cr.width/2, y: cr.y + cr.height/2 } : null
                    };
                }
            """), timeout=3.0)

            if bet_info.get('pp'):
                px = bet_info['pp']['x'] + iframe_ox
                py = bet_info['pp']['y'] + iframe_oy
                await top_page.mouse.click(px, py)
                print(f"      [{_ts()}] [zone] #pp_bet clicked at ({px:.0f},{py:.0f}) ✓")
                await asyncio.sleep(0.5)
            else:
                print(f"      [{_ts()}] [zone] #pp_bet not found")

            if bet_info.get('confirm'):
                cx2 = bet_info['confirm']['x'] + iframe_ox
                cy2 = bet_info['confirm']['y'] + iframe_oy
                await top_page.mouse.click(cx2, cy2)
                print(f"      [{_ts()}] [zone] confirm clicked at ({cx2:.0f},{cy2:.0f}) ✓")
                print(f"      [{_ts()}] [place-bet] DONE ✓")
                return True
            else:
                print(f"      [{_ts()}] [zone] confirm button not found")
                return False

        except Exception as e:
            print(f"      [{_ts()}] [zone] bet+confirm failed: {e}")
            return False

    except Exception as e:
        print(f"      [place-bet] UNHANDLED EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return False


async def _post_overlay_event(event_name):
    try:
        payload = json.dumps({
            "event": event_name,
            "timestamp": datetime.datetime.now().isoformat(),
        }).encode("utf-8")
        print(f"      [overlay-event] CALLING https://bota-parsing.xman.agency/api/round-startt payload={payload.decode('utf-8')}")
        req = urllib.request.Request(
            "https://bota-parsing.xman.agency/api/round-startt",
            data=payload, method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "User-Agent": "bota4-bot/1.0", "Content-Length": str(len(payload))},
        )
        status, body = await asyncio.to_thread(
            lambda: (lambda r: (r.status, r.read(200).decode("utf-8", errors="replace")))(
                urllib.request.urlopen(req, timeout=5)
            )
        )
        print(f"      [overlay-event] POST event={event_name!r} status={status} {body[:80]!r}")
    except Exception as e:
        print(f"      [overlay-event] POST failed: {e}")


# ═════════════════════════════════════════════════════════════════════════════
#  PAGE HEALTH CHECK
# ═════════════════════════════════════════════════════════════════════════════

async def _is_page_healthy(game_page):
    try:
        # Check frames for chip — game may be in iframe
        for target in [game_page] + list(game_page.frames):
            try:
                chip_count = await target.locator("#C_1000, [id^='C_']").count()
                if chip_count > 0:
                    return True, "ok"
            except Exception:
                pass

        # No chip found anywhere — check if page has visible elements at all
        body_empty = await game_page.evaluate(
            "() => { const allEls = document.querySelectorAll('*'); let v = 0; "
            "for (const el of allEls) { if (el === document.body || el === document.documentElement) continue; "
            "const r = el.getBoundingClientRect(); if (r.width > 10 && r.height > 10) { v++; } "
            "if (v >= 3) return false; } return true; }"
        )
        if body_empty:
            return False, "black-screen (no visible elements)"

        return False, "chip #C_1000 missing"
    except Exception as e:
        return False, f"eval-error: {e}"

async def _recover_game_page(game_page, wall, check_interval=10):
    async def _wait_for_chip(target_page, label, timeout_sec=30):
        print(f"[{wall:6.1f}s] [recovery] waiting for chip ({label})...")
        for attempt in range(timeout_sec):
            try:
                if await target_page.locator("#C_1000, [id^='C_']").count() > 0:
                    print(f"[{wall:6.1f}s] [recovery] chip ready ✓ ({label})")
                    return True
            except Exception:
                pass
            if attempt % 5 == 0:
                try: print(f"[{wall:6.1f}s] [recovery]   url={target_page.url[:70]}")
                except Exception: pass
            await asyncio.sleep(1)
        return False

    async def _navigate_via_go_room(target_page, label):
        print(f"[{wall:6.1f}s] [recovery] [{label}] navigating to live-casino...")
        for _nav_attempt in range(3):
            try:
                await target_page.goto("https://staging.xman.agency/all-games/live-casino",
                    wait_until="domcontentloaded", timeout=60000)
                await target_page.wait_for_timeout(3000)
                break
            except Exception as _nav_e:
                await asyncio.sleep(2)

        lobby_page, bota_ok = await _click_bota(target_page, target_page.context)
        if not bota_ok:
            print(f"[{wall:6.1f}s] [recovery] [{label}] Bota not found")
            return False

        landed_page, go_ok = await _click_go_room(lobby_page, lobby_page.context, ROOM_ID)
        if not go_ok:
            print(f"[{wall:6.1f}s] [recovery] [{label}] goRoom failed")
            return False

        print(f"[{wall:6.1f}s] [recovery] [{label}] landed: {landed_page.url[:70]}")
        for i in range(15):
            if "gaming-tg.com" in landed_page.url:
                break
            await asyncio.sleep(1)

        if landed_page is not target_page:
            if await _wait_for_chip(landed_page, f"{label}-new-tab", timeout_sec=30):
                try:
                    await target_page.goto(landed_page.url, wait_until="domcontentloaded", timeout=60000)
                except Exception:
                    pass
                return await _wait_for_chip(target_page, f"{label}-sync", timeout_sec=20)
            return False

        return await _wait_for_chip(target_page, label, timeout_sec=30)

    print(f"\n[{wall:6.1f}s] [recovery] ── STEP 1 ──")
    try:
        if await _navigate_via_go_room(game_page, "step1"):
            print(f"[{wall:6.1f}s] [recovery] ✅ Step 1 SUCCESS")
            return True
    except Exception as e:
        print(f"[{wall:6.1f}s] [recovery] Step 1 ERROR: {e}")

    print(f"\n[{wall:6.1f}s] [recovery] ── STEP 2: re-auth ──")
    try:
        await game_page.goto("https://staging.xman.agency/", wait_until="domcontentloaded", timeout=60000)
        login_btn = game_page.locator("button.register-button")
        if await login_btn.count() > 0:
            await login_btn.first.click()
            await game_page.wait_for_timeout(2000)
            await game_page.locator(
                "input[type='text'],input[name*='user'],input[id*='user'],input[name*='id'],input[id*='id']"
            ).first.fill(LOGIN_USERNAME)
            await game_page.wait_for_timeout(500)
            await game_page.locator("input[type='password']").first.fill(LOGIN_PASSWORD)
            await game_page.locator("button[type='submit']").first.click()
            await game_page.wait_for_timeout(3000)

        if await _navigate_via_go_room(game_page, "step2"):
            print(f"[{wall:6.1f}s] [recovery] ✅ Step 2 SUCCESS")
            return True
    except Exception as e:
        print(f"[{wall:6.1f}s] [recovery] Step 2 ERROR: {e}")

    print(f"\n[{wall:6.1f}s] [recovery] ❌ ALL STEPS FAILED")
    return False


async def _diagnose(top_page, game_frame, label="diag"):
    ts = datetime.datetime.now().strftime("%H%M%S")
    fname = f"diag_{label}_{ts}.png"
    try: await top_page.screenshot(path=fname); print(f"      [diag] {fname}")
    except Exception as e: print(f"      [diag] screenshot failed: {e}")
    print(f"      [diag] frames: {[f.url[:80] for f in top_page.frames]}")


# ═════════════════════════════════════════════════════════════════════════════
#  MAIN SESSION
# ═════════════════════════════════════════════════════════════════════════════

async def run_session_async():
    relay = relay_port = None
    cdp_port = _find_free_port(19400)

    if PROXY_MODE == "residential":
        up_host, up_port = DEFAULT_PROXY_IP.rsplit(":", 1); up_port = int(up_port)
        up_user, up_pass = DEFAULT_PROXY_USER, DEFAULT_PROXY_PASS
        label = f"{DEFAULT_PROXY_IP} (residential)"
    elif PROXY_MODE == "datacenter":
        up_host, up_port, up_user, up_pass = _pick_datacenter_proxy()
        if not up_host:
            raise RuntimeError(f"No proxies in {PROXY_TXT_PATH}")
        label = f"{up_host}:{up_port} (datacenter)"
    else:
        up_host = None; label = "(direct)"

    if up_host:
        relay_port = _find_free_port(18400)
        relay = AuthRelay(relay_port, up_host, int(up_port), up_user or "", up_pass or "")
        relay.start()
        print(f"[relay] :{relay_port} → {label}")
    else:
        print(f"[proxy] {label}")

    print(f"[chrome] {CHROME_PATH}")
    chrome_proc, _ = launch_chrome_with_cdp(relay_port, cdp_port)

    try:
        if not wait_for_cdp_ready(cdp_port):
            raise RuntimeError("CDP not ready")
        print("[chrome] CDP ready")

        pw = await async_playwright().start()
        try:
            browser = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            try:
                await ctx.set_extra_http_headers({"Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8"})
            except Exception:
                pass
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()

            print("[1/7] Navigate to xman.agency ...")
            await page.goto("https://staging.xman.agency/", wait_until="domcontentloaded", timeout=60000)
            print(f"      {await page.title()}")

            print("[2/7] Login button ...")
            await page.locator("button.register-button").first.click()
            await page.wait_for_timeout(2000)

            print("[3/7] Credentials ...")
            await page.locator(
                "input[type='text'],input[name*='user'],input[id*='user'],"
                "input[name*='id'],input[id*='id']"
            ).first.fill(LOGIN_USERNAME)
            await page.wait_for_timeout(500)
            await page.locator("input[type='password']").first.fill(LOGIN_PASSWORD)

            print("[4/7] Submit ...")
            await page.locator("button[type='submit']").first.click()
            await page.wait_for_timeout(3000)
            print(f"      post-login: {page.url}")

            print("[5/7] Live Casino ...")
            for _nav_attempt in range(3):
                try:
                    await page.goto("https://staging.xman.agency/all-games/live-casino",
                        wait_until="domcontentloaded", timeout=60000)
                    await page.wait_for_timeout(3000)
                    print(f"      live casino loaded ✓  url={page.url[:70]}")
                    break
                except Exception as nav_e:
                    await asyncio.sleep(2)

            print("[6/7] Click Bota image ...")
            lobby_page, bota_ok = await _click_bota(page, ctx)
            if not bota_ok:
                raise RuntimeError("Bota image not found on live-casino page")

            print(f"      [6/7] Bota lobby: {lobby_page.url[:70]}")
            print(f"      [6/7] Clicking goRoom({ROOM_ID})...")
            after_go_room_page, go_ok = await _click_go_room(lobby_page, ctx, ROOM_ID)
            if not go_ok:
                raise RuntimeError(f"goRoom({ROOM_ID}) failed")

            print(f"      [6/7] After goRoom: {after_go_room_page.url[:70]}")
            print("[7/7] Locating gaming-tg.com page and waiting for chip...")

            game_page = None
            for attempt in range(10):  # reduced from 60 — game is in iframe, not separate tab
                for p in ctx.pages:
                    try:
                        if "gaming-tg.com" in p.url and not p.is_closed():
                            chip_count = await p.locator("#C_1000, [id^='C_']").count()
                            if chip_count > 0:
                                game_page = p
                                print(f"      [{attempt}s] gaming-tg.com + chip ✓  url={p.url[:70]}")
                                break
                    except Exception:
                        pass
                if game_page:
                    break
                if attempt % 10 == 0:
                    all_urls = [p.url[:70] for p in ctx.pages if not p.is_closed()]
                    print(f"      [{attempt}s] open pages: {all_urls}")
                await asyncio.sleep(1)

            if not game_page:
                # Game is likely inside an iframe on seam.zisego.com
                # Find the seam page and use it as game_page
                for p in ctx.pages:
                    if not p.is_closed() and ('zisego' in p.url or 'seam' in p.url):
                        # Check if any frame has the chip
                        for f in p.frames:
                            try:
                                chip_count = await f.locator("#C_1000, [id^='C_']").count()
                                if chip_count > 0:
                                    game_page = p
                                    print(f"      [WARN] chip found in iframe of seam page: {p.url[:70]}")
                                    break
                            except Exception:
                                pass
                        if game_page:
                            break

            if not game_page:
                game_page = after_go_room_page
                print(f"      [WARN] chip not found after 60s — using: {game_page.url[:70]}")
                await _diagnose(game_page, None, "no-chip")

            # Find the game frame — target the view?idx frame specifically
            game_frame = game_page.main_frame
            for f in game_page.frames:
                try:
                    furl = f.url
                    # Primary: match the game view URL
                    if 'view?idx' in furl or 'view2?idx' in furl:
                        game_frame = f
                        print(f"      [frame] game frame by URL: {furl[:70]}")
                        break
                    # Secondary: frame has game_msg AND container
                    has_game = await f.evaluate("""
                        () => !!(
                            document.getElementById('game_msg') &&
                            document.getElementById('container') &&
                            document.getElementById('btn_submit')
                        )
                    """)
                    if has_game:
                        game_frame = f
                        print(f"      [frame] game frame by elements: {furl[:70]}")
                        break
                except Exception:
                    pass
            poll_frame = game_frame
            print(f"      [frame] using game_frame url={game_frame.url[:70]}")

            # Cache iframe offset once — avoids repeated slow evaluate calls during betting
            _iframe_ox, _iframe_oy = 0.0, 0.0
            try:
                _iframe_ox, _iframe_oy = await _get_iframe_offset(game_frame, game_page)
                print(f"      [frame] iframe offset cached: ({_iframe_ox:.0f}, {_iframe_oy:.0f})")
            except Exception as e:
                print(f"      [frame] iframe offset failed: {e}")

            print("[track] Monitoring. Ctrl+C to stop.\n")

            CHIP_TESTID             = "chip-stack-value-1000"
            POLL_INTERVAL           = 0.5
            WINDOW_OPEN_TIMEOUT_SEC = 300

            elapsed = round_count = 0
            prev_is_open = prev_showing_res = False
            prev_cd_int = prev_road_count = 0
            prev_overlay_state = None
            now = asyncio.get_event_loop().time
            last_open_time = bet_open_at = now()
            bet_cd = None
            session_start = now()
            last_badge_round_id = None
            last_game_cnt = None
            last_bet_game_cnt = None
            captured_result_keys = set()
            result_capture_armed = False
            result_capture_round = 0
            result_armed_signature = None
            result_armed_at = now()
            last_black_screen_check = now()
            consecutive_unhealthy = 0

            while True:
                await asyncio.sleep(POLL_INTERVAL)
                elapsed += 1
                wall = now() - session_start

                if now() - last_black_screen_check >= BLACK_SCREEN_CHECK_INTERVAL:
                    last_black_screen_check = now()
                    healthy, health_reason = await _is_page_healthy(game_page)
                    if not healthy:
                        consecutive_unhealthy += 1
                        print(f"\n[{wall:6.1f}s] [health] ⚠️  UNHEALTHY #{consecutive_unhealthy}: {health_reason}")
                        if consecutive_unhealthy >= 2:
                            recovered = await _recover_game_page(game_page, wall, BLACK_SCREEN_CHECK_INTERVAL)
                            if recovered:
                                consecutive_unhealthy = 0
                                last_open_time = now()
                                prev_is_open = prev_showing_res = False
                                prev_cd_int = prev_road_count = 0
                                last_badge_round_id = None
                                last_black_screen_check = now()
                                result_capture_armed = False
                                result_armed_at = now()
                                print(f"[{wall:6.1f}s] [health] ✅ recovery complete")
                            else:
                                print(f"[{wall:6.1f}s] [health] ❌ recovery failed — restarting...")
                                try: await pw.stop()
                                except Exception: pass
                                try: chrome_proc.terminate(); chrome_proc.wait(timeout=5)
                                except Exception: pass
                                if relay: relay.stop()
                                await asyncio.sleep(3)
                                _restart_script()
                    else:
                        if consecutive_unhealthy > 0:
                            print(f"\n[{wall:6.1f}s] [health] ✅ healthy again")
                        else:
                            print(f"[{wall:6.1f}s] [health] ✅ ok | url={game_page.url[:60]}")
                        consecutive_unhealthy = 0

                is_open, cd, dbg = await _read_wrapper_state(game_frame)
                result_txt  = (dbg.get('result')    or '') if isinstance(dbg, dict) else ''
                p_score     = (dbg.get('pScore')    or '') if isinstance(dbg, dict) else ''
                b_score     = (dbg.get('bScore')    or '') if isinstance(dbg, dict) else ''
                road_count  = (dbg.get('roadCount') or 0)  if isinstance(dbg, dict) else 0
                timer_src   = (dbg.get('src')       or '') if isinstance(dbg, dict) else ''
                showing_res = bool(dbg.get('showingResult')) if isinstance(dbg, dict) else False

                current_round_id = None
                timer_open, timer_val, badge_round_id = await _read_betting_timer(game_frame)
                explicit_round_id = await _read_round_id(game_frame)
                if explicit_round_id:
                    badge_round_id = explicit_round_id
                if badge_round_id:
                    current_round_id = badge_round_id
                    last_badge_round_id = badge_round_id
                elif last_badge_round_id:
                    current_round_id = last_badge_round_id

                if timer_open and timer_val:
                    is_open = True
                    cd = str(timer_val)
                    cd_int = timer_val
                else:
                    cd_int = int(cd) if cd and str(cd).isdigit() else 0

                result_probe = await _read_result_cards(game_frame)
                _debug_tick = (elapsed % 4 == 0)

                if _debug_tick:
                    sig = result_probe.get("signature")
                    print(f"\n[{wall:6.1f}s] [capture-debug]"
                          f" armed={result_capture_armed} armed_round={result_capture_round}"
                          f" ready={result_probe.get('captureReady')} reason={result_probe.get('reason')}"
                          f" ctx={result_probe.get('context')} roots={result_probe.get('rootCount')}"
                          f" Pboxes={result_probe.get('playerBoxCount')} Bboxes={result_probe.get('bankerBoxCount')}"
                          f" open={result_probe.get('openCardCount')}"
                          f" Ps={result_probe.get('playerScore', result_probe.get('playerScoreText'))}"
                          f" Bs={result_probe.get('bankerScore', result_probe.get('bankerScoreText'))}"
                          f" sig={(sig or '')[:80]} current_round_id={current_round_id!r}"
                          f" frame_url={game_frame.url[:50]}")

                if result_probe.get("captureReady"):
                    showing_res = True
                    p_score = result_probe.get("playerScore")
                    b_score = result_probe.get("bankerScore")
                    result_signature = result_probe.get("signature")
                    capture_key = f"{result_capture_round}:{result_signature or current_round_id or round_count}"

                    if not result_capture_armed:
                        if _debug_tick:
                            print(f"\n[{wall:6.1f}s] [result-ready-skip] capture not armed round={round_count}")
                    elif result_armed_signature and result_signature == result_armed_signature:
                        if _debug_tick:
                            print(f"\n[{wall:6.1f}s] [result-ready-skip] same signature round={round_count}")
                    elif capture_key not in captured_result_keys:
                        captured_result_keys.add(capture_key)
                        pc = [c.get("code") or "unknown" for c in result_probe.get("playerCards", [])]
                        bc = [c.get("code") or "unknown" for c in result_probe.get("bankerCards", [])]
                        print(f"\n[{wall:6.1f}s] RESULT HTML READY ctx={result_probe.get('context')}"
                              f" round={round_count} P={pc} ({result_probe.get('playerScore')})"
                              f" B={bc} ({result_probe.get('bankerScore')})")
                        # Take screenshot directly from the game frame showing .item_result
                        try:
                            target_frame = None
                            for _f in game_page.frames:
                                if 'view?idx' in _f.url or 'view2?idx' in _f.url:
                                    target_frame = _f
                                    break
                            if target_frame is None:
                                target_frame = game_frame
                            await target_frame.locator('.item_result').screenshot(
                                path=f"screenshots/round{round_count:04d}_tresult_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                            )
                            fname = f"screenshots/round{round_count:04d}_tresult_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                            print(f"      [screenshot] saved result element: {fname}")
                            upload_round_id = str(int(current_round_id) - 1) if current_round_id and str(current_round_id).isdigit() else current_round_id
                            if upload_round_id and upload_round_id not in _uploaded_round_ids:
                                _uploaded_round_ids.add(upload_round_id)
                                await _post_round_image(fname, upload_round_id)
                        except Exception as _e:
                            print(f"      [screenshot] element screenshot failed: {_e}")
                            await _take_screenshot(game_page, round_count, "result",
                                round_id=current_round_id, result_data=result_probe)
                        result_capture_armed = False
                        result_armed_signature = None

                elif _debug_tick:
                    print(f"\n[{wall:6.1f}s] [result-scan] ctx={result_probe.get('context')}"
                          f" reason={result_probe.get('reason')}"
                          f" roots={result_probe.get('rootCount')}"
                          f" Pcards={len(result_probe.get('playerCards', []))}"
                          f" Bcards={len(result_probe.get('bankerCards', []))}"
                          f" url={(result_probe.get('url') or '')[:70]}")

                if result_capture_armed and (now() - result_armed_at) > RESULT_ARMED_TIMEOUT_SEC:
                    print(f"\n[{wall:6.1f}s] [screenshot] TIMEOUT — forcing screenshot round={result_capture_round}")
                    await _deep_dom_audit(game_page, f"missed_r{result_capture_round}")
                    await _take_screenshot(game_page, result_capture_round, "timeout", round_id=current_round_id)
                    result_capture_armed = False
                    result_armed_at = now()

                if showing_res and not prev_showing_res:
                    bal = await _read_balance(game_page)
                    print(f"\n[{wall:6.1f}s] ROUND END #{round_count} winner={result_txt!r} P={p_score} B={b_score} bal={bal!r}")

                road_gained = road_count - prev_road_count
                if road_gained > 0 and not result_capture_armed:
                    result_capture_armed = True
                    result_capture_round = round_count or road_count
                    result_armed_signature = None
                    result_armed_at = now()
                    print(f"\n[{wall:6.1f}s] [capture-debug] armed by road +{road_gained}")
                if road_gained > 0 and not (showing_res and not prev_showing_res):
                    bal = await _read_balance(game_page)
                    print(f"\n[{wall:6.1f}s] ROAD +{road_gained} road={road_count} result={result_txt!r} bal={bal!r}")

                overlay_gone  = prev_showing_res and not showing_res
                cd_jumped     = is_open and cd_int > prev_cd_int + 10
                window_opened = overlay_gone or (is_open and not prev_is_open) or cd_jumped
                trigger = ("overlay-gone" if overlay_gone
                           else f"cd-jump({prev_cd_int}->{cd_int})" if cd_jumped else "open")

                # Detect new round by game_cnt increment
                if current_round_id and current_round_id != last_game_cnt:
                    if last_game_cnt is not None and not window_opened:
                        window_opened = True
                        trigger = f"game_cnt({last_game_cnt}->{current_round_id})"
                    last_game_cnt = current_round_id

                if window_opened:
                    round_count += 1
                    print(f"\n[{wall:6.1f}s] ROUND START #{round_count} [{trigger}] "
                          f"game_cnt={current_round_id!r} timer={cd}s")
                    
                    last_open_time = bet_open_at = now()
                    bet_cd = cd
                    if not result_capture_armed:
                        result_capture_armed = True
                        result_capture_round = round_count
                        result_armed_at = now()
                        last_open_time = bet_open_at = now()
                        result_armed_signature = result_probe.get("signature") if result_probe.get("captureReady") else None
                    else:
                        result_capture_round = round_count

                    print(f"\n[{wall:6.1f}s] [capture-debug] armed by round start round={round_count}")
                    print(f"\n[{wall:6.1f}s] ROUND START #{round_count} [{trigger}] timer={cd}s — BETTING")

                    # _round = round_count
                    # _bet_cd = bet_cd
                    # _current_rid = await _read_round_id(game_frame) or current_round_id

                    _round = round_count
                    _bet_cd = bet_cd
                    _current_rid = await _read_round_id(game_frame) or current_round_id

                    # Dedup synchronously BEFORE scheduling — prevents race condition
                    if _current_rid and _current_rid == last_bet_game_cnt:
                        print(f"      [round-task] SKIP (pre-schedule) — already processed game_cnt={_current_rid}")
                    else:
                        last_bet_game_cnt = _current_rid

                        async def _run_round_tasks(rc=_round, bc=_bet_cd, rid=_current_rid):
                            print(f"      [round-task] round={rc} waiting for 배팅시작...")
                            detected = await _wait_for_betting_started(game_page, timeout_sec=55)

                            if detected:
                                # Screenshot IMMEDIATELY — previous round cards visible now
                                await asyncio.sleep(0.2)
                                latest_rid = await _read_round_id(game_frame) or rid
                                await _take_screenshot(game_page, rc, "betting_started", round_id=latest_rid)

                                # Wait 5s AFTER screenshot, before placing bet
                                print(f"      [round-task] waiting 5s before placing bet...")
                                await asyncio.sleep(5)

                                bet_round_id = latest_rid or current_round_id
                                await _place_bet(game_page, game_frame, poll_frame,
                                            bet_open_at, bc, round_id=bet_round_id,
                                            iframe_ox=_iframe_ox, iframe_oy=_iframe_oy)
                                return

                            print(f"      [round-task] 배팅시작 timeout — attempting bet anyway")
                            latest_rid = await _read_round_id(game_page) or rid
                            await _take_screenshot(game_page, rc, "timeout_bet", round_id=latest_rid)
                            bet_round_id = latest_rid or current_round_id
                            await _place_bet(game_page, game_frame, poll_frame,
                                            bet_open_at, bc, round_id=bet_round_id,
                                            iframe_ox=_iframe_ox, iframe_oy=_iframe_oy)
                            return
                        asyncio.ensure_future(_run_round_tasks())

                since = now() - last_open_time
                if since >= WINDOW_OPEN_TIMEOUT_SEC:
                    print(f"\n[{wall:6.1f}s] [WARN] No bet window for {since:.0f}s — diagnosing")
                    await _diagnose(game_page, game_frame, "no-window")
                    last_open_time = now()

                overlay_state = None
                targets = [game_page]
                for target in targets:
                    try:
                        result = await target.evaluate("""
                            () => {
                                for (const el of document.querySelectorAll('[class*="overlay"]')) {
                                    const t = (el.innerText || el.textContent || '').trim().toUpperCase();
                                    if (t !== 'SHUFFLE' && t !== 'LIVE') continue;
                                    const style = window.getComputedStyle(el);
                                    const isHidden = (style.display === 'none' ||
                                        style.visibility === 'hidden' || style.opacity === '0');
                                    let parent = el.parentElement; let parentHidden = false;
                                    while (parent && parent !== document.body) {
                                        const ps = window.getComputedStyle(parent);
                                        if (ps.display === 'none' || ps.visibility === 'hidden' ||
                                            ps.opacity === '0') { parentHidden = true; break; }
                                        parent = parent.parentElement;
                                    }
                                    if (!isHidden && !parentHidden) {
                                        if (t === 'SHUFFLE') return 'SHUFFLE';
                                        if (t === 'LIVE') return 'LIVE';
                                    }
                                }
                                return null;
                            }
                        """)
                        if result in ('SHUFFLE', 'LIVE'):
                            overlay_state = result
                            break
                    except Exception:
                        pass

                if overlay_state == 'SHUFFLE' and prev_overlay_state != 'SHUFFLE':
                    print(f"\n[{wall:6.1f}s] SHUFFLE DETECTED — posting event")
                    await _post_overlay_event('SHUFFLE')

                    async def _wait_for_live_after_shuffle():
                        while True:
                            await asyncio.sleep(30)
                            try:
                                current = None
                                for target in [game_page] + list(game_page.frames):
                                    try:
                                        r = await target.evaluate("""
                                            () => {
                                                for (const el of document.querySelectorAll('[class*="overlay"]')) {
                                                    const t = (el.innerText||el.textContent||'').trim().toUpperCase();
                                                    if (t !== 'SHUFFLE' && t !== 'LIVE') continue;
                                                    const s = window.getComputedStyle(el);
                                                    if (s.display==='none'||s.visibility==='hidden'||s.opacity==='0') continue;
                                                    if (t === 'SHUFFLE') return 'SHUFFLE';
                                                    if (t === 'LIVE') return 'LIVE';
                                                }
                                                return null;
                                            }
                                        """)
                                        if r in ('SHUFFLE', 'LIVE'): current = r; break
                                    except Exception: pass
                                print(f"      [shuffle-poll] overlay={current!r}")
                                if current == 'LIVE':
                                    await _post_overlay_event('live')
                                    _recovery_wall = asyncio.get_event_loop().time() - session_start
                                    await _recover_game_page(game_page, _recovery_wall)
                                    return
                                elif current != 'SHUFFLE':
                                    return
                            except Exception as e:
                                print(f"      [shuffle-poll] error: {e}")

                    asyncio.ensure_future(_wait_for_live_after_shuffle())

                elif overlay_state == 'LIVE' and prev_overlay_state == 'SHUFFLE':
                    print(f"\n[{wall:6.1f}s] SHUFFLE END / LIVE — posting event")
                    await _post_overlay_event('live')

                prev_overlay_state = overlay_state
                prev_is_open     = is_open
                prev_showing_res = showing_res
                prev_cd_int      = cd_int
                prev_road_count  = road_count

                if elapsed % 10 == 0:
                    chip_val = await _read_chip_value(game_page, CHIP_TESTID)
                    balance  = await _read_balance(game_page)
                    state = "RESULT" if showing_res else "BETTING" if is_open else "DEALING"
                    print(f"[{wall:6.1f}s] {state} round={round_count} cd={cd!r}"
                          f" timer={timer_val!r} overlay={showing_res} road={road_count}"
                          f" P={p_score} B={b_score} result={result_txt!r}"
                          f" chip={chip_val!r} bal={balance!r}")
                else:
                    state = "RES" if showing_res else "BET" if is_open else "---"
                    print(f"[{wall:6.1f}s] {state} cd={cd!r} timer={timer_val!r}"
                          f" overlay={showing_res} road={road_count} P={p_score} B={b_score}", end="\r")

        finally:
            try: await pw.stop()
            except Exception: pass
    finally:
        if relay: relay.stop()
        try: chrome_proc.terminate()
        except Exception: pass


def main():
    try:
        asyncio.run(run_session_async())
    except KeyboardInterrupt:
        print("\n[stopped]")

if __name__ == "__main__":
    main()