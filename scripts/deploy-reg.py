"""Upload a built static site to REG.RU using certificate-verified FTPS."""

import argparse
import ftplib
import getpass
import os
from pathlib import Path
import ssl
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    source = args.source.resolve()
    if not (source / "index.html").is_file():
        raise SystemExit("Source must be an Astro dist directory with index.html")
    host = os.environ.get("REG_FTP_HOST", "server209.hosting.reg.ru")
    user = os.environ.get("REG_FTP_USER", "u3698579")
    password = os.environ.get("REG_FTP_PASSWORD") or getpass.getpass("FTPS password: ")
    destination = os.environ.get("REG_FTP_DIR", "/www/bonatlas.ru")
    def connect():
        ftp = ftplib.FTP_TLS(context=ssl.create_default_context(), timeout=60)
        ftp.connect(host)
        ftp.login(user, password)
        ftp.prot_p()
        ftp.cwd(destination)
        return ftp

    if args.check:
        with connect() as ftp:
            print(f"Connected to {host}; destination {ftp.pwd()}", flush=True)
            print("Existing files: " + ", ".join(ftp.nlst()), flush=True)
        return
    files = sorted(p for p in source.rglob("*") if p.is_file())
    # Put the home page last, after its styles and images are available.
    files.sort(key=lambda p: p == source / "index.html")
    ftp = None
    try:
        for number, path in enumerate(files):
            relative = path.relative_to(source)
            # Short sessions avoid shared-hosting connection lifetime limits.
            if ftp is not None and number % 10 == 0:
                ftp.close()
                ftp = None
            for attempt in range(3):
                try:
                    if ftp is None:
                        ftp = connect()
                    ftp.cwd(destination)
                    for part in relative.parts[:-1]:
                        try:
                            ftp.mkd(part)
                        except ftplib.error_perm as exc:
                            if not str(exc).startswith("550"):
                                raise
                        ftp.cwd(part)
                    temporary = f".deploy-{path.name}"
                    with path.open("rb") as stream:
                        ftp.storbinary(f"STOR {temporary}", stream)
                    if ftp.size(temporary) != path.stat().st_size:
                        raise OSError(f"Upload size mismatch: {relative}")
                    ftp.rename(temporary, path.name)
                    break
                except (OSError, EOFError, ftplib.error_temp, ftplib.error_proto):
                    if ftp is not None:
                        ftp.close()
                        ftp = None
                    if attempt == 2:
                        raise
                    print(f"Retrying {relative.as_posix()} after connection error", flush=True)
                    time.sleep(2 * (attempt + 1))
            print(f"Uploaded {relative.as_posix()}", flush=True)
        print(f"Uploaded {len(files)} files. No remote files deleted.", flush=True)
    finally:
        if ftp is not None:
            ftp.close()


if __name__ == "__main__":
    main()
