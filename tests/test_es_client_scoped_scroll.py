from __future__ import annotations

import unittest
from unittest import mock

from es_rag_tuner.es_client import (
    Connection,
    PrivateIndexAccessError,
    bind_local_owner,
    index_scroll_scope,
    private_alias,
    private_read_scope,
    request,
    reset_local_owner,
)


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b"{}"


class ScopedScrollAccessTests(unittest.TestCase):
    def setUp(self):
        self.connection = Connection("http://127.0.0.1:1")

    def test_root_scroll_requires_index_scope(self):
        with self.assertRaisesRegex(PrivateIndexAccessError, "Index-scoped"):
            request(self.connection, "POST", "_search/scroll", {"scroll_id": "opaque"})

    def test_checked_shared_index_scope_allows_root_scroll_endpoint(self):
        with mock.patch("es_rag_tuner.es_client.urllib.request.urlopen", return_value=_Response()) as open_url:
            with index_scroll_scope("shared-documents"):
                self.assertEqual(
                    request(self.connection, "POST", "_search/scroll", {"scroll_id": "opaque"}),
                    {},
                )
        self.assertTrue(open_url.call_args.args[0].full_url.endswith("/_search/scroll"))

    def test_private_index_scroll_scope_requires_private_read_capability(self):
        owner_token = bind_local_owner("a" * 32)
        self.addCleanup(reset_local_owner, owner_token)
        alias = private_alias("a" * 32)
        with self.assertRaises(PrivateIndexAccessError):
            with index_scroll_scope(alias):
                self.fail("private scope should not open without the read capability")

        with mock.patch("es_rag_tuner.es_client.urllib.request.urlopen", return_value=_Response()):
            with private_read_scope(), index_scroll_scope(alias):
                self.assertEqual(request(self.connection, "POST", "_search/scroll", {"scroll_id": "opaque"}), {})


if __name__ == "__main__":
    unittest.main()
