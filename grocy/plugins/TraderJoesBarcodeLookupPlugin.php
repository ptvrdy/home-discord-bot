<?php

use Grocy\Helpers\BaseBarcodeLookupPlugin;
use Grocy\Services\DatabaseService;
use Grocy\Services\StockService;

/*
	Trader Joe's barcode lookup for Grocy (companion to the Rosie Discord bot).

	Enabled via docker-compose.yml, which also mounts Rosie's data folder
	read-only at /rosie:
		GROCY_STOCK_BARCODE_LOOKUP_PLUGIN=TraderJoesBarcodeLookupPlugin
		ROSIE_DB=/rosie/<Rosie's database file>

	Trader Joe's-brand barcodes are "00" + the last 5 digits of TJ's SKU + a
	GS1 check digit (e.g. Garlic Butter Nut Mix: SKU 083372 -> 00833721). For
	those, the item is looked up in the copy of the TJ's catalog Rosie keeps
	(re-synced monthly) - traderjoes.com itself blocks requests from Grocy. The
	new product gets TJ's name, a home location / shelf life / product group
	from TJ's category, and TJ's price on the barcode so the Purchase page
	pre-fills it. Rosie adds the product photo within ~10 minutes.

	The shelf-life rules come from Rosie's database too: she stores the rules
	from her config/shelf_life.py there on every startup, so that file is the
	one place to change them.

	Anything else (name-brand items), or anything not in the catalog, falls
	through to Grocy's built-in Open Food Facts plugin, exactly as before.
*/

class TraderJoesBarcodeLookupPlugin extends BaseBarcodeLookupPlugin
{
	public const PLUGIN_NAME = "Trader Joe's (falls back to Open Food Facts)";

	// Used only if Rosie hasn't stored her rules yet: Pantry, never expires.
	private const DEFAULT_SHELF_LIFE = ['Pantry', -1, -1];

	protected function ExecuteLookup($barcode)
	{
		$sku = self::SkuFromBarcode($barcode);
		$db = $sku === null ? null : self::RosieDb();
		$item = $db === null ? null : self::CatalogItem($db, $sku);
		if ($item === null)
		{
			return $this->OpenFoodFactsLookup($barcode);
		}

		[$locationName, $days, $freezerDays] = self::ShelfLife(self::ShelfLifeRules($db), $item['category'], $item['subcategory']);
		$output = [
			'name' => trim($item['name']),
			'location_id' => $this->LocationId($locationName),
			'qu_id_purchase' => $this->QuantityUnitId(),
			'qu_id_stock' => $this->QuantityUnitId(),
			'__qu_factor_purchase_to_stock' => 1,
			'__barcode' => $barcode,
			'default_best_before_days' => $days,
			'default_best_before_days_after_freezing' => $freezerDays,
			'default_best_before_days_after_thawing' => $days === -1 ? 0 : 1,
		];

		$groupId = self::ProductGroupId($item['category']);
		if ($groupId !== null)
		{
			$output['product_group_id'] = $groupId;
		}

		if (is_numeric($item['price']))
		{
			self::StorePriceOnBarcode($barcode, (float)$item['price']);
		}

		return $output;
	}

	// "00" + 5 SKU digits + check digit; scanners may report it as 8, 12, or 13 digits.
	private static function SkuFromBarcode($barcode)
	{
		$digits = preg_replace('/\D/', '', (string)$barcode);
		if (strlen($digits) > 8)
		{
			if (ltrim(substr($digits, 0, -8), '0') !== '')
			{
				return null;
			}
			$digits = substr($digits, -8);
		}
		if (strlen($digits) !== 8 || substr($digits, 0, 2) !== '00')
		{
			return null;
		}

		$sum = 0;
		$body = strrev(substr($digits, 0, 7));
		for ($i = 0; $i < 7; $i++)
		{
			$sum += intval($body[$i]) * ($i % 2 === 0 ? 3 : 1);
		}
		if ((10 - $sum % 10) % 10 !== intval($digits[7]))
		{
			return null;
		}

		return '0' . substr($digits, 2, 5);
	}

	// Rosie's database, opened read-only.
	private static function RosieDb()
	{
		$path = getenv('ROSIE_DB');
		if (empty($path) || !is_readable($path))
		{
			return null;
		}
		try
		{
			$db = new \PDO('sqlite:' . $path, null, null, [\PDO::SQLITE_ATTR_OPEN_FLAGS => \PDO::SQLITE_OPEN_READONLY]);
			$db->setAttribute(\PDO::ATTR_ERRMODE, \PDO::ERRMODE_EXCEPTION);
			return $db;
		}
		catch (\Throwable $error)
		{
			return null;
		}
	}

	// Items TJ's has since dropped still count (old packages keep their
	// barcodes), current ones first.
	private static function CatalogItem($db, $sku)
	{
		try
		{
			$query = $db->prepare('SELECT name, category, subcategory, price FROM tj_products WHERE sku = ? ORDER BY discontinued_at IS NOT NULL LIMIT 1');
			$query->execute([$sku]);
			$row = $query->fetch(\PDO::FETCH_ASSOC);
			return $row === false ? null : $row;
		}
		catch (\Throwable $error)
		{
			return null;
		}
	}

	// The rules from Rosie's config/shelf_life.py, as she stored them on
	// startup: [{category, subcategory|null, location, days, freezer_days}],
	// checked in order. -1 days = never expires.
	private static function ShelfLifeRules($db)
	{
		try
		{
			$query = $db->prepare("SELECT value FROM bot_state WHERE key = 'shelf_life_rules'");
			$query->execute();
			$rules = json_decode((string)$query->fetchColumn(), true);
			return is_array($rules) ? $rules : [];
		}
		catch (\Throwable $error)
		{
			return [];
		}
	}

	private function OpenFoodFactsLookup($barcode)
	{
		$path = dirname((new \ReflectionClass(StockService::class))->getFileName()) . '/../plugins/OpenFoodFactsBarcodeLookupPlugin.php';
		require_once $path;
		return (new \OpenFoodFactsBarcodeLookupPlugin($this->Locations, $this->QuantityUnits, $this->UserSettings))->Lookup($barcode);
	}

	private static function ShelfLife($rules, $category, $subcategory)
	{
		foreach ($rules as $rule)
		{
			if (($rule['category'] ?? null) === $category && (($rule['subcategory'] ?? null) === null || $rule['subcategory'] === $subcategory))
			{
				return [$rule['location'], (int)$rule['days'], (int)$rule['freezer_days']];
			}
		}
		return self::DEFAULT_SHELF_LIFE;
	}

	private function LocationId($name)
	{
		foreach ($this->Locations as $location)
		{
			if ($location->name === $name)
			{
				return $location->id;
			}
		}
		if ($this->UserSettings['product_presets_location_id'] != -1)
		{
			return $this->UserSettings['product_presets_location_id'];
		}
		return $this->Locations[0]->id;
	}

	private function QuantityUnitId()
	{
		foreach ($this->QuantityUnits as $unit)
		{
			if (in_array($unit->name, ['Piece', 'Pieces', 'Pack', 'Unit', 'Each'], true))
			{
				return $unit->id;
			}
		}
		if ($this->UserSettings['product_presets_qu_id'] != -1)
		{
			return $this->UserSettings['product_presets_qu_id'];
		}
		return $this->QuantityUnits[0]->id;
	}

	private static function ProductGroupId($category)
	{
		if (empty($category))
		{
			return null;
		}
		try
		{
			$db = DatabaseService::GetInstance()->GetDbConnection();
			$group = $db->product_groups()->where('name = :1', $category)->fetch();
			if ($group === null)
			{
				$group = $db->product_groups()->createRow(['name' => $category]);
				$group->save();
			}
			return $group->id;
		}
		catch (\Throwable $error)
		{
			return null;
		}
	}

	// Grocy creates the product and its barcode row right after this plugin
	// returns, in the same request - so set the barcode's last_price (which
	// the Purchase page pre-fills) once the request has finished.
	private static function StorePriceOnBarcode($barcode, $price)
	{
		register_shutdown_function(static function () use ($barcode, $price)
		{
			try
			{
				$row = DatabaseService::GetInstance()->GetDbConnection()->product_barcodes()->where('barcode = :1', $barcode)->fetch();
				if ($row !== null && empty($row->last_price))
				{
					$row->update(['last_price' => $price]);
				}
			}
			catch (\Throwable $error)
			{
				// Best effort: the price is a convenience, not required.
			}
		});
	}
}
