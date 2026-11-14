"""Serve the included production build using only Python's standard library."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import errno
import webbrowser


def main():
    dist = Path(__file__).resolve().parent / "dist"
    if not (dist / "index.html").is_file():
        raise SystemExit("dist/index.html topilmadi. ZIP faylni to'liq oching.")
    handler = partial(SimpleHTTPRequestHandler, directory=str(dist))
    server = None
    for port in range(3000, 3011):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), handler)
            break
        except OSError as error:
            if error.errno != errno.EADDRINUSE and getattr(error, "winerror", None) != 10048:
                raise
    if server is None:
        raise SystemExit("3000-3010 portlari band. Boshqa mahalliy serverni yoping.")
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"\nTerraMind AI: {url}\nOynani ochiq qoldiring. To'xtatish: Ctrl+C.\n", flush=True)
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDemo server to'xtatildi.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
