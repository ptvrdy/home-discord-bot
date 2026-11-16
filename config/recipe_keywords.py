RECIPE_KEYWORDS = {

    "chicken": {
        "category": "protein",
        "include": [
            "chicken",
        ],
        "exclude": [
            "chicken broth",
            "chicken stock",
            "chicken bouillon",
        ]
    },

    "beef": {
        "category": "protein",
        "include": [
            "beef",
            "steak",
            "ground beef",
            "corned beef",
            "brisket",
            "roast beef",
            "short ribs",
            "sirloin",
            "chuck roast",
            "ribeye",
            "beef tenderloin",
        ],
        "exclude": [
            "beef broth",
            "beef stock",
            "beef bouillon",
        ]
    },

    "pork": {
        "category": "protein",
        "include": [
            "pork",
            "sausage",
            "bacon",
            "ham",
        ],
        "exclude": []
    },

    "tofu": {
        "category": "protein",
        "include": [
            "tofu"
        ],
        "exclude": []
    },

    "pasta": {
        "category": "type",
        "include": [
            "pasta",
            "spaghetti",
            "linguine",
            "penne",
            "tortellini",
            "fettuccine",
            "macaroni",
            "ravioli",
            "lasagna",
            "noodles",
            "rotini",
            "cavatappi",
            "orzo",
            "farfalle",
            "fusilli",
            "tagliatelle",
            "capellini",
            "gemelli",
            "bucatini",
            "pappardelle",
            "cavatelli",
            "ziti",
            "vermicelli",
            "conchiglie",
            "campanelle",
            "orecchiette",
            "tortelloni",
            "manicotti",
            "gnocchi",
            "fagioli",
            "egg noodles",
            "lasagne",
        ],
        "exclude": []
    },

    "seafood": {
        "category": "protein",
        "include": [
            "fish", "shrimp", "prawn", "crab", "lobster", "tuna", "salmon", "anchovy",
        ],
        "exclude": [],
    },

    "one_pot": {
        "category": "method",
        "include": [
            "one pot", "one-pot", "one pan", "one-pan", "one skillet", "one-skillet",
            "sheet pan", "sheet-pan",
        ],
        "exclude": [],
    },

    "slow_cooker": {
        "category": "method",
        "include": ["slow cooker", "crockpot", "crock pot"],
        "exclude": [],
    },

    "breakfast": {
        "category": "meal",
        "include": [
            "breakfast", "brunch", "pancake", "waffle", "omelet", "omelette",
            "muesli", "granola", "oatmeal", "cereal",
        ],
        "exclude": [],
    },

    "lunch": {
        "category": "meal",
        "include": ["lunch"],
        "exclude": [],
    },

    "dinner": {
        "category": "meal",
        "include": ["dinner", "supper"],
        "exclude": [],
    },

    "soup": {
        "category": "type",
        "include": ["soup", "stew", "chowder", "bisque", "chili"],
        "exclude": [],
    },

    # An occasion tag is mostly one you add on purpose (it's in the /tags menu),
    # so auto-tagging is deliberately conservative: only unmistakable phrases,
    # not "turkey" or "stuffing" alone (ground turkey tacos, stuffed peppers).
    "thanksgiving": {
        "category": "occasion",
        "include": [
            "thanksgiving",
            "roast turkey", "whole turkey", "turkey gravy",
            "cranberry sauce",
            "green bean casserole", "sweet potato casserole",
            "pumpkin pie",
            "turkey stuffing", "bread stuffing", "cornbread stuffing",
        ],
        "exclude": [
            "pumpkin pie spice",
        ],
    },

    "dessert": {
        "category": "type",
        "include": [
            "cake", "cupcake", "cheesecake",
            "ice cream", "gelato", "sorbet",
            "pudding", "custard", "mousse",
            "brownie", "brownies",
            "cookie", "cookies",
            "tart", "pie",
            "candy", "fudge",
            "cobbler", "crumble",
            "donut", "doughnut",
            "macaron", "meringue",
        ],
        "exclude": [
            "fish cake", "crab cake", "salmon cake", "rice cake", "corn cake",
            "shepherd's pie", "shepherds pie", "pot pie", "chicken pot pie",
            "tamale pie", "meat pie",
            "yorkshire pudding", "black pudding", "blood pudding",
        ],
    },

}
