"""Grocy REST API client - the pantry's source of truth for what's in stock.

Grocy is self-hosted (see the grocy/ docker-compose setup), so unlike
OurGroceries there's no third party to be polite to; it's still only called
when someone does something, or from the once-a-day expiry check.

Optional integration: if GROCY_URL / GROCY_API_KEY aren't set, `Grocy()`
raises GrocyNotConfigured and callers quietly skip pantry features, the same
way OurGroceries features degrade without credentials.
"""

import base64
import os
from datetime import date

import httpx

TIMEOUT_SECONDS = 10.0


class GrocyNotConfigured(RuntimeError):
    pass


class GrocyError(RuntimeError):
    pass


def grocy_configured() -> bool:
    return bool(os.getenv("GROCY_URL") and os.getenv("GROCY_API_KEY"))


class Grocy:
    """Thin async wrapper over the endpoints Rosie needs. Every method maps
    to exactly one Grocy API call."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None, client: httpx.AsyncClient | None = None):
        base_url = base_url or os.getenv("GROCY_URL")
        api_key = api_key or os.getenv("GROCY_API_KEY")
        if not base_url or not api_key:
            raise GrocyNotConfigured("GROCY_URL and GROCY_API_KEY must be set in .env")
        self.base_url = base_url.rstrip("/") + "/api"
        self._client = client or httpx.AsyncClient(
            headers={"GROCY-API-KEY": api_key, "Accept": "application/json"},
            timeout=TIMEOUT_SECONDS,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        await self.aclose()

    async def _request(self, method: str, path: str, **kwargs):
        try:
            response = await self._client.request(method, f"{self.base_url}{path}", **kwargs)
        except httpx.HTTPError as error:
            raise GrocyError(f"couldn't reach Grocy ({error.__class__.__name__})") from error
        if response.status_code >= 400:
            try:
                message = response.json().get("error_message") or response.text
            except ValueError:
                message = response.text
            raise GrocyError(f"Grocy said: {message[:300]}")
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    # --- generic objects (products, locations, quantity units, groups) ---

    async def get_objects(self, entity: str) -> list[dict]:
        return await self._request("GET", f"/objects/{entity}")

    async def create_object(self, entity: str, data: dict) -> int:
        result = await self._request("POST", f"/objects/{entity}", json=data)
        return int(result["created_object_id"])

    async def update_object(self, entity: str, object_id: int, data: dict) -> None:
        await self._request("PUT", f"/objects/{entity}/{object_id}", json=data)

    async def get_userfields(self, entity: str, object_id: int) -> dict:
        return await self._request("GET", f"/userfields/{entity}/{object_id}") or {}

    async def set_userfields(self, entity: str, object_id: int, values: dict) -> None:
        await self._request("PUT", f"/userfields/{entity}/{object_id}", json=values)

    async def upload_product_picture(self, file_name: str, content: bytes) -> None:
        encoded = base64.b64encode(file_name.encode()).decode()
        await self._request(
            "PUT",
            f"/files/productpictures/{encoded}",
            content=content,
            headers={"Content-Type": "application/octet-stream"},
        )

    # --- stock ---

    async def get_stock(self) -> list[dict]:
        """Every product currently in stock: [{"product_id", "amount",
        "best_before_date", "product": {...}}, ...]."""
        return await self._request("GET", "/stock")

    async def get_product_details(self, product_id: int) -> dict:
        return await self._request("GET", f"/stock/products/{product_id}")

    async def get_volatile_stock(self, due_soon_days: int = 2) -> dict:
        """{"due_products", "overdue_products", "expired_products", "missing_products"}."""
        return await self._request("GET", "/stock/volatile", params={"due_soon_days": due_soon_days})

    async def add_stock(
        self,
        product_id: int,
        amount: float,
        price: float | None = None,
        best_before_date: date | None = None,
        location_id: int | None = None,
    ) -> str:
        """Returns the transaction ID (for undo)."""
        body: dict = {"amount": amount, "transaction_type": "purchase"}
        if price is not None:
            body["price"] = price
        if best_before_date is not None:
            body["best_before_date"] = best_before_date.isoformat()
        if location_id is not None:
            body["location_id"] = location_id
        result = await self._request("POST", f"/stock/products/{product_id}/add", json=body)
        return _transaction_id(result)

    async def consume(self, product_id: int, amount: float, spoiled: bool = False) -> str:
        result = await self._request(
            "POST",
            f"/stock/products/{product_id}/consume",
            json={"amount": amount, "spoiled": spoiled, "transaction_type": "consume"},
        )
        return _transaction_id(result)

    async def open_product(self, product_id: int, amount: float = 1) -> str:
        result = await self._request("POST", f"/stock/products/{product_id}/open", json={"amount": amount})
        return _transaction_id(result)

    async def transfer(self, product_id: int, amount: float, location_from: int, location_to: int) -> str:
        result = await self._request(
            "POST",
            f"/stock/products/{product_id}/transfer",
            json={"amount": amount, "location_id_from": location_from, "location_id_to": location_to},
        )
        return _transaction_id(result)

    async def edit_stock_entry(self, entry: dict, **changes) -> None:
        """Change fields of one stock entry (a row from get_objects("stock")),
        resending its other editable fields unchanged."""
        body = {
            key: entry.get(key)
            for key in ("amount", "best_before_date", "price", "open", "location_id", "purchased_date")
        }
        body.update(changes)
        await self._request("PUT", f"/stock/entry/{entry['id']}", json=body)

    async def merge_products(self, keep_id: int, remove_id: int) -> None:
        """Grocy's own merge: moves the removed product's stock, history, and
        barcodes onto the kept product, then deletes the removed one."""
        await self._request("POST", f"/stock/products/{keep_id}/merge/{remove_id}")

    async def undo_transaction(self, transaction_id: str) -> None:
        await self._request("POST", f"/stock/transactions/{transaction_id}/undo")


def _transaction_id(result) -> str:
    """Stock actions return the stock_log rows they created; every row from
    one action shares a transaction_id, which is what undo takes."""
    rows = result if isinstance(result, list) else [result]
    for row in rows:
        if isinstance(row, dict) and row.get("transaction_id"):
            return row["transaction_id"]
    raise GrocyError("Grocy didn't return a transaction ID")
