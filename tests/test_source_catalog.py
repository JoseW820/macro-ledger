from app.providers.source_catalog import check_source


def test_check_source_reports_http_status(monkeypatch):
    class Headers:
        def get(self, key, default=""):
            return "text/html"

    class Response:
        status = 200
        headers = Headers()
        def __enter__(self): return self
        def __exit__(self, *args): return False

    monkeypatch.setattr("app.providers.source_catalog.urlopen", lambda request, timeout: Response())
    result = check_source("demo", "https://example.test")
    assert result.status == 200
    assert result.content_type == "text/html"
