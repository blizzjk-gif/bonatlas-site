"""Small certificate-verified FTPS transport with reconnects and atomic file uploads."""
import ftplib
import getpass
import io
import os
from pathlib import PurePosixPath
import ssl
import time
import tempfile
from pathlib import Path


class Transport:
    def __init__(self):
        self.password = os.environ.get("REG_FTP_PASSWORD") or getpass.getpass("FTPS password: ")
        self.ftp = None
        self.operations = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self.ftp is not None:
            self.ftp.close()
            self.ftp = None

    def connection(self):
        if self.operations >= 8:
            self.close()
            self.operations = 0
        if self.ftp is None:
            self.ftp = ftplib.FTP_TLS(context=ssl.create_default_context(), timeout=60)
            self.ftp.connect(os.environ.get("REG_FTP_HOST", "server209.hosting.reg.ru"))
            self.ftp.login(os.environ.get("REG_FTP_USER", "u3698579"), self.password)
            self.ftp.prot_p()
        self.operations += 1
        return self.ftp

    def retry(self, operation):
        for attempt in range(3):
            try:
                return operation(self.connection())
            except (OSError, EOFError, ftplib.error_temp, ftplib.error_proto):
                self.close()
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))

    def exists(self, path):
        return self.size(path) is not None or self.is_dir(path)

    def is_dir(self, path):
        def check(ftp):
            try:
                ftp.cwd(path)
                return True
            except ftplib.error_perm:
                return False
            finally:
                ftp.cwd("/")
        return self.retry(check)

    def size(self, path):
        def check(ftp):
            try:
                ftp.voidcmd("TYPE I")
                return ftp.size(path)
            except ftplib.error_perm as exc:
                if str(exc).startswith("550"):
                    return None
                raise
        return self.retry(check)

    def mkdir(self, path):
        def create(ftp):
            current = ""
            for part in PurePosixPath(path).parts[1:]:
                current += "/" + part
                try:
                    ftp.mkd(current)
                except ftplib.error_perm as exc:
                    if not str(exc).startswith("550"):
                        raise
        return self.retry(create)

    def upload(self, local, target):
        self.mkdir(str(PurePosixPath(target).parent))
        def send(ftp):
            temporary = str(PurePosixPath(target).with_name('.deploy-' + PurePosixPath(target).name))
            with local.open("rb") as stream:
                ftp.storbinary("STOR " + temporary, stream)
            if ftp.size(temporary) != local.stat().st_size:
                raise OSError(f"Size mismatch for {target}")
            ftp.rename(temporary, target)
        self.retry(send)

    def read(self, path):
        def read_bytes(ftp):
            output = io.BytesIO()
            ftp.retrbinary("RETR " + path, output.write)
            return output.getvalue()
        return self.retry(read_bytes)

    def rename(self, source, destination):
        # Never retry a directory move blindly: its first result may be unknown.
        ftp = self.connection()
        try:
            ftp.rename(source, destination)
        except (OSError, EOFError, ftplib.error_temp, ftplib.error_proto):
            self.close()
            if not self.exists(source) and self.exists(destination):
                return
            raise

    def list_dirs(self, path):
        def listing(ftp):
            return [name for name, facts in ftp.mlsd(path) if facts.get("type") == "dir"]
        return self.retry(listing)

    def list_files(self, path):
        return self.retry(lambda ftp: list(ftp.mlsd(path)))

    def write(self, target, data):
        with tempfile.TemporaryDirectory(prefix="bon-upload-") as directory:
            local = Path(directory) / "file"
            local.write_bytes(data)
            self.upload(local, target)

    def copy(self, source, target):
        self.write(target, self.read(source))

    def delete(self, path):
        def remove(ftp):
            try:
                ftp.delete(path)
            except ftplib.error_perm as exc:
                if not str(exc).startswith("550"):
                    raise
        self.retry(remove)
