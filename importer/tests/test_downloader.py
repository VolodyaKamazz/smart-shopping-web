import httpx
from django.test import SimpleTestCase

from importer.downloader import download_feed, make_client

from .helpers import make_client as fake_client

URL = "http://shop.example/feed.yml"


class DownloadFeedTests(SimpleTestCase):
    def test_gives_file_with_body_at_start(self):
        body = b"x" * 200_000
        with download_feed(URL, fake_client({URL: body})) as feed:
            self.assertEqual(feed.read(), body)

    def test_file_is_closed_after_block(self):
        with download_feed(URL, fake_client({URL: b"<yml_catalog/>"})) as feed:
            pass
        self.assertTrue(feed.closed)

    def test_follows_redirect(self):
        def handler(request):
            if request.url.path == "/old.yml":
                return httpx.Response(301, headers={"Location": "http://shop.example/new.yml"})
            return httpx.Response(200, content=b"<yml_catalog/>")
        client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
        with download_feed("http://shop.example/old.yml", client) as feed:
            self.assertEqual(feed.read(), b"<yml_catalog/>")

    def test_error_status_raises_on_enter(self):
        with self.assertRaises(httpx.HTTPStatusError), download_feed(URL, fake_client({URL: 404})):
            self.fail("блок не должен выполняться")

    def test_network_errors_raise_http_error(self):
        for error in (httpx.ConnectError("нет связи"), httpx.ReadTimeout("таймаут")):
            with self.subTest(error=type(error).__name__), self.assertRaises(httpx.HTTPError), \
                    download_feed(URL, fake_client({URL: error})):
                self.fail("блок не должен выполняться")

    def test_real_client_has_timeout_and_user_agent(self):
        with make_client() as client:
            self.assertEqual(client.timeout.read, 30.0)
            self.assertEqual(client.timeout.connect, 10.0)
            self.assertIn("SmartShopping", client.headers["User-Agent"])