import json
import unittest

import httpx

from services.grocy import Grocy, GrocyError, GrocyNotConfigured


def _grocy(handler) -> Grocy:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Grocy("http://grocy.test/", "key", client=client)


class GrocyClientTests(unittest.IsolatedAsyncioTestCase):
    def test_requires_configuration(self):
        with self.assertRaises(GrocyNotConfigured):
            Grocy(base_url="", api_key="")

    async def test_add_stock_returns_transaction_id(self):
        seen = {}

        def handler(request: httpx.Request):
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json=[{"id": 1, "transaction_id": "abc"}])

        async with _grocy(handler) as grocy:
            transaction = await grocy.add_stock(5, 2, price=3.49)

        self.assertEqual(transaction, "abc")
        self.assertEqual(seen["url"], "http://grocy.test/api/stock/products/5/add")
        self.assertEqual(seen["body"], {"amount": 2, "transaction_type": "purchase", "price": 3.49})

    async def test_create_object_returns_new_id(self):
        def handler(request):
            return httpx.Response(200, json={"created_object_id": "42"})

        async with _grocy(handler) as grocy:
            self.assertEqual(await grocy.create_object("products", {"name": "Egg"}), 42)

    async def test_errors_carry_grocys_message(self):
        def handler(request):
            return httpx.Response(400, json={"error_message": "Amount to be consumed cannot be > current stock amount"})

        async with _grocy(handler) as grocy:
            with self.assertRaisesRegex(GrocyError, "cannot be > current stock"):
                await grocy.consume(5, 99)

    async def test_no_content_responses(self):
        def handler(request):
            return httpx.Response(204)

        async with _grocy(handler) as grocy:
            self.assertIsNone(await grocy.undo_transaction("abc"))

    async def test_picture_upload_encodes_file_name(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["type"] = request.headers["content-type"]
            return httpx.Response(204)

        async with _grocy(handler) as grocy:
            await grocy.upload_product_picture("tj-1.png", b"png-bytes")

        self.assertTrue(seen["url"].endswith("/api/files/productpictures/dGotMS5wbmc="))
        self.assertEqual(seen["type"], "application/octet-stream")


if __name__ == "__main__":
    unittest.main()
