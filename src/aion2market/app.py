"""Desktop app: the price service and the dashboard in one process, shown in its own window.

This is what the released .exe runs. During development the separate commands
(``service run`` + ``dashboard``) in a browser are easier and stay as they are.

    python -m aion2market.app             # own window (pywebview / Edge WebView2)
    python -m aion2market.app --browser   # same, but in the default browser

Data lives in %LOCALAPPDATA%\\aion2market (market.db, app.log) unless --db or AION2_DB says otherwise.
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

APP_NAME = "Aion 2 Market"
NPCAP_URL = "https://npcap.com/#download"


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "aion2market"


def _ask(title: str, text: str, yes_no: bool = False) -> bool:
    from tkinter import Tk, messagebox
    root = Tk()
    root.withdraw()
    try:
        if yes_no:
            return messagebox.askyesno(title, text, parent=root)
        messagebox.showinfo(title, text, parent=root)
        return True
    finally:
        root.destroy()


def npcap_installed() -> bool:
    return (Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "Npcap").is_dir()


def ensure_keylog() -> Path | None:
    """The key file the game's libcurl writes to; offers to set SSLKEYLOGFILE on first run."""
    from .service import DEFAULT_KEYLOG, default_keylog
    if default_keylog() != DEFAULT_KEYLOG:          # already set (environment or registry)
        return default_keylog()
    path = data_dir() / "sslkeys.log"
    if not _ask(APP_NAME,
                "Market fiyatlarını okuyabilmek için oyunun TLS anahtarlarını bir dosyaya yazması gerekiyor "
                "(SSLKEYLOGFILE kullanıcı ortam değişkeni).\n\n"
                f"Dosya: {path}\n\n"
                "Not: Chrome, Edge ve Firefox da bu değişkene uyar ve kendi anahtarlarını aynı dosyaya yazar. "
                "Dosyayı kimseyle paylaşma.\n\nAyarlansın mı?", yes_no=True):
        return None
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "SSLKEYLOGFILE", 0, winreg.REG_EXPAND_SZ, str(path))
    announce_environment()
    _ask(APP_NAME, "Ayarlandı. Steam'i tamamen kapatıp yeniden aç (sistem tepsisinden Çıkış), sonra oyuna gir.\n\n"
                   "Fiyatlar yine gelmezse bilgisayarı bir kez yeniden başlat.")
    return path


def announce_environment() -> None:
    """Tell Explorer the user environment changed. Without this, programs started from it
    (Steam, then the game) only see SSLKEYLOGFILE after signing out and in again."""
    try:
        import ctypes
        HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
                                                 SMTO_ABORTIFHUNG, 5000, None)
    except (OSError, AttributeError):
        pass


def run_service(db: Path, stop_file: Path, keylog: Path | None) -> None:
    """Live capture when possible; otherwise, or when it fails, the background sources so that
    item names, shared prices and aion2.exchange keep coming in."""
    from . import service
    from .store import Store
    if keylog is not None:
        try:
            service.main(["--db", str(db), "run", "--keylog", str(keylog), "--stop-file", str(stop_file)])
            return
        except Exception as e:                       # Npcap in admin-only mode, missing driver, ...
            import traceback
            traceback.print_exc()
            reason = f"{type(e).__name__}: {e}"
    else:
        reason = "SSLKEYLOGFILE ayarlanmadı"
    store = Store(db)
    try:
        store.set_meta("capture.error", reason[:200])
    finally:
        store.close()
    service.run_background(db, stop_file)


def _log_to_file(path: Path) -> None:
    # A windowed exe has no console: sys.stdout is None and print() output would be lost.
    path.parent.mkdir(parents=True, exist_ok=True)
    log = open(path, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--popup"]:            # notification cards; alerts.PopupHost starts us like this when frozen
        from . import popup
        return popup.main(argv[1:])

    ap = argparse.ArgumentParser(description=f"{APP_NAME}: fiyat servisi + arayüz tek pencerede.")
    ap.add_argument("--db", type=Path, default=None, help="SQLite dosyası (varsayılan: %%LOCALAPPDATA%%\\aion2market)")
    ap.add_argument("--browser", action="store_true", help="kendi penceresi yerine tarayıcıda aç")
    ap.add_argument("--no-service", action="store_true", help="sadece arayüz, paket dinleme yok")
    args = ap.parse_args(argv)

    db = args.db or Path(os.environ.get("AION2_DB") or data_dir() / "market.db")
    os.environ["AION2_DB"] = str(db)         # dashboard.db_path() reads this
    if getattr(sys, "frozen", False):
        _log_to_file(db.parent / "app.log")

    from . import dashboard, service

    stop_file = db.parent / "app.stop"
    stop_file.unlink(missing_ok=True)
    worker = None
    if not args.no_service:
        if not npcap_installed():
            # The installer explains Npcap and the window shows its status, so no dialog on every start.
            worker = threading.Thread(target=service.run_background, args=(db, stop_file), daemon=True)
        else:
            worker = threading.Thread(target=run_service, args=(db, stop_file, ensure_keylog()), daemon=True)
        worker.start()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"Arayüz: {url}  veritabanı: {db}", flush=True)
    try:
        if args.browser:
            webbrowser.open(url)
            threading.Event().wait()         # until Ctrl+C
        else:
            try:
                import webview
                webview.create_window(APP_NAME, url, width=1400, height=900, min_size=(900, 600))
                webview.start()
            except Exception:                 # no WebView2 runtime (older Windows 10): use the browser instead
                import traceback
                traceback.print_exc()
                webbrowser.open(url)
                _ask(APP_NAME, "Uygulama penceresi açılamadı (Microsoft Edge WebView2 eksik olabilir), "
                               "arayüz tarayıcıda açıldı.\n\nUygulamayı kapatmak için Tamam'a bas.")
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
        if worker is not None:
            stop_file.touch()
            worker.join(5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
