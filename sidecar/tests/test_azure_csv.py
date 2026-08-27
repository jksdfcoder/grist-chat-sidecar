from app.azure_csv import AdlsAzureCsv, parse_blobfuse_azstorage


def test_parse_blobfuse_azstorage():
    got = parse_blobfuse_azstorage(
        """
components:
  - azstorage
azstorage:
  type: adls
  account-name: dlshkuhklibdl01
  container: fshkuhklibdl01
  mode: key
  account-key: secret
"""
    )
    assert got["account-name"] == "dlshkuhklibdl01"
    assert got["container"] == "fshkuhklibdl01"
    assert got["type"] == "adls"
    assert got["account-key"] == "secret"


def test_adls_write_uses_if_match():
    from azure.core import MatchConditions

    calls = {}

    class Fake:
        def upload_data(self, data, overwrite=None, **kw):
            calls["data"] = data
            calls["overwrite"] = overwrite
            calls.update(kw)

        def get_file_properties(self):
            return type("P", (), {"etag": '"9"'})()

    azure = AdlsAzureCsv("acct", "cont", "key", "p.csv")
    azure._file = lambda: Fake()  # type: ignore[method-assign]
    etag = azure.write("x", if_match="1")
    assert calls["data"] == b"x"
    assert calls["overwrite"] is True
    assert calls["etag"] == "1"
    assert calls["match_condition"] == MatchConditions.IfNotModified
    assert etag == "9"
