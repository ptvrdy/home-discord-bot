# OurGroceries unofficial API — notes from reverse-engineering it

OurGroceries has no official public API. This documents what we learned while building
[`services/grocery_list.py`](../services/grocery_list.py), a real integration in this
project, in case it saves someone else the same digging. Corrections welcome — none of
this is officially confirmed by OurGroceries, all of it is inferred from source code and
cross-checking independent implementations.

## What we used

The [`ourgroceries`](https://pypi.org/project/ourgroceries/) PyPI package
([source](https://github.com/ljmerza/py-our-groceries)), version `1.5.4`. It's an asyncio
wrapper that authenticates the same way the mobile app does — username/password login via
a form POST, then a session cookie — and issues everything else as JSON POSTs to a single
endpoint (`/your-lists/`) with a `command` field selecting the action (e.g. `getOverview`,
`getList`, `insertItem`).

## Confirmed response shapes

Verified two ways: reading the library's own source directly, and cross-checking against
[Home Assistant's production `ourgroceries` integration](https://github.com/home-assistant/core/tree/dev/homeassistant/components/ourgroceries)
(`coordinator.py`, `todo.py`), which uses the same library in front of real accounts.

**`get_my_lists()`**
```jsonc
{
  "shoppingLists": [
    { "id": "...", "name": "...", "versionId": "..." },
    // ...
  ]
}
```

**`get_list_items(list_id)`**
```jsonc
{
  "list": {
    "items": [
      { "id": "...", /* text field - see below */ },
      // ...
    ],
    "versionId": "..."
  }
}
```

## Two things that aren't what they look like

**1. Crossed-off status is not reliably under `crossedOff`.**

The `ourgroceries` library normalizes every item with:
```python
item[ATTR_ITEM_CROSSED] = item.get(ATTR_ITEM_CROSSED, False)  # ATTR_ITEM_CROSSED = 'crossedOff'
```
This *looks* like it guarantees a `crossedOff` boolean, but it only preserves that key if
the raw server response already used it — otherwise it silently defaults to `False`. Home
Assistant's actual production code reads a **different** field instead:
```python
item.get("crossedOffAt", False)
```
i.e. a timestamp (or falsy) field, not a boolean. We couldn't fully confirm which one the
live API actually returns without testing against a real account, so
[`_is_crossed_off()`](../services/grocery_list.py) checks both:
```python
return bool(item.get("crossedOff") or item.get("crossedOffAt"))
```
If you build against this library and rely on crossed-off detection, don't trust the
library's own default — check `crossedOffAt` too.

**2. An item's text has been seen under both `value` and `name`.**

The library sends `value` when *creating* an item (`ATTR_ITEM_VALUE = 'value'` in the
outgoing payload), but that's not necessarily the field name used when the item comes back
in a `get_list_items()` response — outgoing and incoming field names for the same concept
aren't guaranteed to match on a reverse-engineered API. We check both defensively:
```python
def _item_text(item: dict) -> str:
    return (item.get("value") or item.get("name") or "").strip()
```

## What we still don't know

Whether `add_item_to_list()` / `add_items_to_list()`'s response includes the newly-created
item's ID. We looked for other independent implementations to cross-check (a Go/Python
project, a JS client, a C# client) but none had it documented at the source level we could
verify, and we didn't want to guess against a real account just to find out.

**Workaround**: rather than depend on that response, we re-fetch the list right after
adding and match the new items by text (case-insensitive) against the confirmed
`get_list_items()` shape above, to get their real IDs for follow-up actions (e.g.
supporting an "undo" that removes exactly what was just added). See
`add_recipe_ingredients()` in [`services/grocery_list.py`](../services/grocery_list.py).
If you figure out the add-response shape, we'd take a PR that removes the extra call.

## Being a good citizen

An OurGroceries developer showed up on a
[Home Assistant GitHub issue](https://github.com/home-assistant/core/issues/105700) about
excessive API usage and asked integrators to poll `get_my_lists()` at most every 60
seconds and avoid unnecessary repeated fetches. They weren't hostile to unofficial
integrations existing — just asked for reasonable usage. Our integration is triggered
per-command (a person clicking things), not a polling loop, but we still follow the same
spirit: e.g. `find_existing_locations()` stops checking further lists as soon as every
ingredient has been located, rather than always scanning every list on the account.
