"""Скачивание YML-фида.

Фид читается потоком кусками и пишется во временный файл, поэтому большой
файл не занимает память ни при скачивании, ни потом при разборе через iterparse.
"""
import logging
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "SmartShoppingImporter/1.0"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
MAX_DOWNLOAD_SECONDS = 45.0
MAX_FEED_BYTES = 200 * 1024 * 1024
RETRY_DELAYS = (1.0, 3.0)
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class DownloadError(Exception):
    pass


def make_client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT})


def is_transient(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRY_STATUSES
    return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError))


def _download(url: str, client: httpx.Client, feed: IO[bytes]) -> None:
    started = time.monotonic()
    size = 0
    with client.stream("GET", url) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > MAX_FEED_BYTES:
                raise DownloadError(f"фид больше {MAX_FEED_BYTES // (1024 * 1024)} МБ")
            if time.monotonic() - started > MAX_DOWNLOAD_SECONDS:
                raise DownloadError(f"фид скачивается дольше {MAX_DOWNLOAD_SECONDS:.0f} с")
            feed.write(chunk)


@contextmanager
def download_feed(url: str, client: httpx.Client) -> Iterator[IO[bytes]]:
    with tempfile.TemporaryFile() as feed:
        for delay in (*RETRY_DELAYS, None):
            feed.seek(0)
            feed.truncate()
            try:
                _download(url, client, feed)
                break
            except httpx.HTTPError as exc:
                if delay is None or not is_transient(exc):
                    raise
                logger.warning("%s: загрузка не удалась (%s), повтор через %.0f с", url, type(exc).__name__, delay)
                time.sleep(delay)
        feed.seek(0)
        yield feed
