import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.tj_catalog import fetch_catalog, parse_products


def _page(items, current_page=1, total_pages=1):
    return {
        "data": {
            "products": {
                "items": items,
                "total_count": len(items),
                "page_info": {"current_page": current_page, "page_size": 100, "total_pages": total_pages},
            }
        }
    }


TRI_TIP = {
    "sku": "090570",
    "item_title": "Santa Maria Tri-Tip Roast",
    "retail_price": "13.99",
    "sales_size": 1,
    "sales_uom_description": "Lb",
    "primary_image": "/content/dam/trjo/products/m20801/90570.png",
    "new_product": "0",
    "availability": "1",
    "category_hierarchy": [
        {"id": 2, "name": "Products", "level": 1},
        {"id": 8, "name": "Food", "level": 2},
        {"id": 122, "name": "Meat, Seafood & Plant-based", "level": 3},
        {"id": 125, "name": "Beef, Pork & Lamb", "level": 4},
    ],
}
SUCCULENT = {
    "sku": "085369",
    "item_title": "Bare Bones Succulent Garden",
    "retail_price": "8.99",
    "new_product": "1",
    "category_hierarchy": [
        {"id": 2, "name": "Products", "level": 1},
        {"id": 203, "name": "Flowers & Plants", "level": 2},
    ],
}


class ParseProductsTests(unittest.TestCase):
    def test_maps_fields_and_categories(self):
        rows, total_pages = parse_products(_page([TRI_TIP], total_pages=26))
        self.assertEqual(total_pages, 26)
        self.assertEqual(
            rows,
            [
                {
                    "sku": "090570",
                    "name": "Santa Maria Tri-Tip Roast",
                    "category": "Meat, Seafood & Plant-based",
                    "subcategory": "Beef, Pork & Lamb",
                    "price": 13.99,
                    "size": "1 Lb",
                    "image_url": "https://www.traderjoes.com/content/dam/trjo/products/m20801/90570.png",
                    "is_new": False,
                }
            ],
        )

    def test_skips_non_grocery_items(self):
        rows, _ = parse_products(_page([TRI_TIP, SUCCULENT]))
        self.assertEqual([row["sku"] for row in rows], ["090570"])

    def test_tolerates_missing_data(self):
        self.assertEqual(parse_products({}), ([], 0))
        rows, _ = parse_products(_page([{"sku": "1", "item_title": "Mystery", "retail_price": None}]))
        self.assertIsNone(rows[0]["price"])


class FetchCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetches_every_page_in_order(self):
        responses = [_page([TRI_TIP], 1, 2), _page([{**TRI_TIP, "sku": "000002"}], 2, 2)]
        client = AsyncMock()
        client.post.side_effect = [MagicMock(json=MagicMock(return_value=body)) for body in responses]

        with patch("services.tj_catalog.asyncio.sleep", new=AsyncMock()):
            rows = await fetch_catalog(client=client)

        self.assertEqual([row["sku"] for row in rows], ["090570", "000002"])
        pages = [call.kwargs["json"]["variables"]["currentPage"] for call in client.post.await_args_list]
        self.assertEqual(pages, [1, 2])


if __name__ == "__main__":
    unittest.main()
