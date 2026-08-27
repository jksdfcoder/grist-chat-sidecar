import os
from pathlib import Path
from typing import Protocol


class EtagMismatch(Exception):
    pass


class AzureCsv(Protocol):
    def read(self) -> tuple[str, str]: ...
    def write(self, body: str, *, if_match: str) -> str: ...


class MemoryAzureCsv:
    def __init__(self, body: str, etag: str = "1"):
        self.body = body
        self.etag = etag

    def read(self) -> tuple[str, str]:
        return self.body, self.etag

    def write(self, body: str, *, if_match: str) -> str:
        if if_match != self.etag:
            raise EtagMismatch
        self.body = body
        self.etag = str(int(self.etag) + 1)
        return self.etag


def parse_blobfuse_azstorage(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    in_az = False
    for raw in text.splitlines():
        if raw.strip().startswith("#") or not raw.strip():
            continue
        if raw.split("#", 1)[0].rstrip() == "azstorage:":
            in_az = True
            continue
        if in_az and raw[0] not in " \t":
            break
        if not in_az or ":" not in raw:
            continue
        k, _, v = raw.strip().partition(":")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


class AdlsAzureCsv:
    def __init__(self, account: str, container: str, key: str, path: str = "powerbi/users.csv"):
        self.account = account
        self.container = container
        self.key = key
        self.path = path

    @classmethod
    def from_blobfuse(cls, path: Path, file_path: str = "powerbi/users.csv"):
        cfg = parse_blobfuse_azstorage(Path(path).read_text())
        key = cfg.get("account-key") or os.environ.get("AZURE_STORAGE_ACCOUNT_KEY") or ""
        account = cfg.get("account-name") or ""
        container = cfg.get("container") or ""
        if not (account and container and key):
            raise RuntimeError("blobfuse azstorage needs account-name, container, account-key")
        return cls(account, container, key, file_path)

    def _file(self):
        from azure.storage.filedatalake import DataLakeServiceClient

        svc = DataLakeServiceClient(
            account_url=f"https://{self.account}.dfs.core.windows.net",
            credential=self.key,
        )
        return svc.get_file_system_client(self.container).get_file_client(self.path)

    def read(self) -> tuple[str, str]:
        f = self._file()
        props = f.get_file_properties()
        etag = str(getattr(props, "etag", "") or "").strip('"')
        body = f.download_file().readall().decode("utf-8-sig")
        return body, etag

    def write(self, body: str, *, if_match: str) -> str:
        from azure.core import MatchConditions
        from azure.core.exceptions import ResourceModifiedError

        f = self._file()
        data = body.encode("utf-8")
        try:
            if if_match:
                f.upload_data(
                    data,
                    overwrite=True,
                    etag=if_match,
                    match_condition=MatchConditions.IfNotModified,
                )
            else:
                f.upload_data(data, overwrite=True)
        except ResourceModifiedError as e:
            raise EtagMismatch from e
        props = f.get_file_properties()
        return str(getattr(props, "etag", "") or "").strip('"')


def summarize_csv(body: str) -> dict:
    import csv
    import io

    rows = list(csv.reader(io.StringIO(body)))
    return {
        "bytes": len(body.encode()),
        "rows": max(0, len(rows) - 1),
        "columns": rows[0] if rows else [],
    }


if __name__ == "__main__":
    import json
    import sys

    root = Path(__file__).resolve().parents[2]
    cfg = Path(sys.argv[1] if len(sys.argv) > 1 else root / ".azure.yaml")
    dest = Path(sys.argv[2] if len(sys.argv) > 2 else root / "data" / "powerbi-users.csv")
    azure = AdlsAzureCsv.from_blobfuse(cfg)
    body, etag = azure.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body)
    print(json.dumps({"etag": etag, "path": str(dest), **summarize_csv(body)}, ensure_ascii=False))
