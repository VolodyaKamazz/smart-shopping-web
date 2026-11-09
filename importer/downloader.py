"""Скачивание YML-фида.

Фид читается потоком кусками и пишется во временный файл, поэтому большой
файл не занимает память ни при скачивании, ни потом при разборе через iterparse.
"""
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO

import httpx

CHUNK_SIZE = 64 * 1024
USER_AGENT = "SmartShoppingImporter/1.0"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def make_client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT})


@contextmanager
def download_feed(url: str, client: httpx.Client) -> Iterator[IO[bytes]]:
    with tempfile.TemporaryFile() as feed:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes(CHUNK_SIZE):
                feed.write(chunk)
        feed.seek(0)
        yield feed