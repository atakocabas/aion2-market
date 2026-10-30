"""Our own notification cards, shown bottom-right above the taskbar.

Runs as a separate process so the packet loop never waits on the UI. It reads
one JSON object per line on stdin and shows a card for each:

    {"kind": "alert", "item": "Pure Odyle", "price": 56470, "target": 57000, "ts": 1761750000}
    {"kind": "info", "title": "Aion 2 market", "body": "..."}

When stdin closes it exits as soon as the visible cards are gone.

    python -m aion2market.popup --demo      # show sample cards
"""
from __future__ import annotations

import ctypes
import json
import queue
import sys
import threading
import time
import tkinter as tk
from datetime import datetime

BG = "#16181d"
BORDER = "#2c2f38"
TEXT = "#f1f2f4"
MUTED = "#8b909c"
GOLD = "#e8b04a"
GREEN = "#4fd18b"
TRACK = "#262a33"

WIDTH = 360            # at 96 DPI
MARGIN = 16
GAP = 10
SHOW_SECONDS = 12.0
FADE_STEPS = 8
FONT = "Segoe UI"


def _fmt(v: float) -> str:
    return f"{v:,.0f}".replace(",", ".")


def _work_area(root: tk.Tk) -> tuple[int, int, int, int]:
    """Screen area without the taskbar (left, top, right, bottom)."""
    if sys.platform == "win32":
        class RECT(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]
        r = RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0):   # SPI_GETWORKAREA
            return r.l, r.t, r.r, r.b
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def _round_corners(win: tk.Toplevel) -> None:
    if sys.platform != "win32":
        return
    try:
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        pref = ctypes.c_int(2)                                    # DWMWCP_ROUND (Windows 11)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref))
    except (AttributeError, OSError):
        pass


def _play_sound() -> None:
    if sys.platform == "win32":
        import winsound
        try:
            winsound.PlaySound("SystemNotification", winsound.SND_ALIAS | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except RuntimeError:
            pass


class Card:
    def __init__(self, host: "Host", msg: dict):
        self.host = host
        s = host.scale
        self.win = w = tk.Toplevel(host.root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.attributes("-alpha", 0.0)
        w.configure(bg=BORDER)

        inner = tk.Frame(w, bg=BG)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Frame(inner, bg=GOLD, width=int(4 * s)).pack(side="left", fill="y")
        body = tk.Frame(inner, bg=BG)
        body.pack(side="left", fill="both", expand=True, padx=(int(14 * s), int(10 * s)), pady=(int(10 * s), 0))

        head = tk.Frame(body, bg=BG)
        head.pack(fill="x")
        if msg.get("kind") == "alert":
            kind = "Favori fırsatı" if msg.get("typical") else "Hedef fiyata ulaştı"
        else:
            kind = msg.get("title", "Bildirim")
        tk.Label(head, text="AION 2 MARKET", font=(FONT, 8, "bold"), fg=GOLD, bg=BG).pack(side="left")
        tk.Label(head, text=f"  ·  {kind}", font=(FONT, 8), fg=MUTED, bg=BG).pack(side="left")
        close = tk.Label(head, text="✕", font=(FONT, 10), fg=MUTED, bg=BG, cursor="hand2")
        close.pack(side="right")
        close.bind("<Enter>", lambda e: close.configure(fg=TEXT))
        close.bind("<Leave>", lambda e: close.configure(fg=MUTED))

        if msg.get("kind") == "alert":
            price, target = float(msg["price"]), float(msg["target"])
            tk.Label(body, text=msg.get("item") or msg.get("item_key", "?"), font=(FONT, 13, "bold"),
                     fg=TEXT, bg=BG, anchor="w").pack(fill="x", pady=(int(4 * s), 0))
            row = tk.Frame(body, bg=BG)
            row.pack(fill="x")
            tk.Label(row, text=_fmt(price), font=(FONT, 22, "bold"), fg=GOLD, bg=BG).pack(side="left")
            tk.Label(row, text=" Kinah / adet", font=(FONT, 9), fg=MUTED, bg=BG).pack(side="left", anchor="s",
                                                                                        pady=(0, int(7 * s)))
            # Favorite deals compare with the 7-day average, target alerts with the user's target.
            ref, ref_label = (float(msg["typical"]), "7 gün ort.") if msg.get("typical") else (target, "Hedef")
            below = (ref - price) / ref * 100 if ref else 0
            info = tk.Frame(body, bg=BG)
            info.pack(fill="x", pady=(0, int(8 * s)))
            tk.Label(info, text=f"{ref_label} {_fmt(ref)}", font=(FONT, 9), fg=MUTED, bg=BG).pack(side="left")
            tk.Label(info, text=f"   ▼ %{below:.1f}".replace(".", ",") + " altında", font=(FONT, 9, "bold"),
                     fg=GREEN, bg=BG).pack(side="left")
            when = datetime.fromtimestamp(float(msg.get("ts") or time.time())).strftime("%H:%M")
            tk.Label(info, text=when, font=(FONT, 9), fg=MUTED, bg=BG).pack(side="right")
        else:
            tk.Label(body, text=msg.get("body", ""), font=(FONT, 11), fg=TEXT, bg=BG, anchor="w", justify="left",
                     wraplength=int((WIDTH - 50) * s)).pack(fill="x", pady=(int(6 * s), int(12 * s)))

        self.bar = tk.Canvas(inner, height=max(2, int(3 * s)), bg=TRACK, highlightthickness=0, bd=0)
        # Under the text, right of the gold accent stripe.
        self.bar.place(relx=0, rely=1.0, relwidth=1.0, anchor="sw", x=int(4 * s), width=-int(4 * s))
        self.fill = self.bar.create_rectangle(0, 0, 0, 10, fill=GOLD, width=0)

        for widget in self._all(w):
            widget.bind("<Button-1>", lambda e: self.dismiss())
        w.update_idletasks()
        self.width = int(WIDTH * s)
        self.height = w.winfo_reqheight() + int(4 * s)
        self.remaining = SHOW_SECONDS
        self.alpha = 0.0
        self.closing = False
        _round_corners(w)

    def _all(self, widget):
        yield widget
        for child in widget.winfo_children():
            yield from self._all(child)

    def hovered(self) -> bool:
        x, y = self.win.winfo_pointerxy()
        return (self.win.winfo_rootx() <= x < self.win.winfo_rootx() + self.width
                and self.win.winfo_rooty() <= y < self.win.winfo_rooty() + self.height)

    def tick(self, dt: float) -> bool:
        """Advance animation/timer; False once the card is gone."""
        if self.closing:
            self.alpha -= 1 / FADE_STEPS
            if self.alpha <= 0:
                self.win.destroy()
                return False
        else:
            self.alpha = min(0.97, self.alpha + 1 / FADE_STEPS)
            if not self.hovered():
                self.remaining -= dt
            if self.remaining <= 0:
                self.closing = True
        self.win.attributes("-alpha", max(self.alpha, 0.0))
        w = self.bar.winfo_width()
        self.bar.coords(self.fill, 0, 0, w * max(self.remaining, 0) / SHOW_SECONDS, 10)
        return True

    def dismiss(self) -> None:
        self.closing = True


class Host:
    def __init__(self, source: "queue.Queue[dict | None]"):
        if sys.platform == "win32":
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except (AttributeError, OSError):
                pass
        self.root = tk.Tk()
        self.root.withdraw()
        self.scale = self.root.winfo_fpixels("1i") / 96
        self.source = source
        self.cards: list[Card] = []
        self.eof = False
        self.last = time.monotonic()

    def layout(self) -> None:
        left, top, right, bottom = _work_area(self.root)
        m, gap = int(MARGIN * self.scale), int(GAP * self.scale)
        y = bottom - m
        for card in reversed(self.cards):          # newest at the bottom
            y -= card.height
            card.win.geometry(f"{card.width}x{card.height}+{right - m - card.width}+{y}")
            y -= gap

    def poll(self) -> None:
        try:
            while True:
                msg = self.source.get_nowait()
                if msg is None:
                    self.eof = True
                    break
                self.cards.append(Card(self, msg))
                self.layout()
                _play_sound()
        except queue.Empty:
            pass
        now = time.monotonic()
        dt, self.last = now - self.last, now
        before = len(self.cards)
        self.cards = [c for c in self.cards if c.tick(dt)]
        if len(self.cards) != before:
            self.layout()
        if self.eof and not self.cards:
            self.root.destroy()
            return
        self.root.after(30, self.poll)

    def run(self) -> None:
        self.root.after(0, self.poll)
        self.root.mainloop()


def _read_stdin(q: queue.Queue) -> None:
    for raw in sys.stdin.buffer:
        try:
            q.put(json.loads(raw.decode("utf-8")))
        except ValueError:
            continue
    q.put(None)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    q: queue.Queue = queue.Queue()
    if "--demo" in argv:
        q.put({"kind": "info", "title": "Deneme", "body": "Bildirimler çalışıyor."})
        q.put({"kind": "alert", "item": "Pure Odyle", "price": 56470, "target": 57000, "ts": time.time()})
        q.put(None)
    else:
        threading.Thread(target=_read_stdin, args=(q,), daemon=True).start()
    Host(q).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
