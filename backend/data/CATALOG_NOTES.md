## Bedroom catalog (added 2026-10-10)

File: `catalog_bedroom.json` (20 products, 5 per category: `bed`, `nightstand`, `dresser`, `desk`). Same schema as `catalog_verified.json`, plus `style.shape: "rect"`. Prices and dimensions were read from each product page on 2026-10-10 and are quoted in `evidence`. IKEA prices come from the page's JSON-LD and IKEA dimensions from the page's measurement list. Walmart prices and dimensions come from the page's `__NEXT_DATA__` product and specification data. Inches were converted at 0.0254 m and rounded half-up to 3 decimals. Dimensions are W x D x H in meters; for beds, D is the head-to-foot length. Images are in `backend/static/product_images/<id>.jpg`.

### Beds
- **Renwick Queen Upholstered Platform Bed Frame with Channel Tufted Headboard**, Navy Blue, Queen (Walmart): $109.99; W 1.575 x D 2.096 x H 1.143 m. <https://www.walmart.com/ip/Renwick-Queen-Upholstered-Bed-Frame-with-Channel-Tufted-Headboard-Navy-Blue/20616613199>
- **TARVA Bed frame**, pine/Luröy, Queen (IKEA) (theme-match): $199.00; W 1.600 x D 2.089 x H 0.921 m. <https://www.ikea.com/us/en/p/tarva-bed-frame-pine-luroey-s29007794/>
- **MALM Bed frame**, dark-brown veneer, Queen (IKEA): $249.00; W 1.680 x D 2.111 x H 1.000 m. <https://www.ikea.com/us/en/p/malm-bed-frame-dark-brown-veneer-s09574367/>
- **BJÖRKSNÄS Bed frame**, birch/birch veneer/Luröy, Queen (IKEA) (theme-match): $499.00; W 1.721 x D 2.149 x H 1.089 m. <https://www.ikea.com/us/en/p/bjoerksnaes-bed-frame-birch-birch-veneer-luroey-s89501715/>
- **TONSTAD Bed frame with storage**, oak veneer, Queen (IKEA) (theme-match): $699.00; W 1.610 x D 2.111 x H 1.159 m. <https://www.ikea.com/us/en/p/tonstad-bed-frame-with-storage-oak-veneer-10489146/>

### Nightstands
- **GRÅFJÄLLET Nightstand**, anthracite (IKEA): $49.99; W 0.451 x D 0.359 x H 0.591 m. <https://www.ikea.com/us/en/p/grafjaellet-nightstand-anthracite-20570221/>
- **TARVA Nightstand**, pine (IKEA) (theme-match): $79.99; W 0.479 x D 0.391 x H 0.619 m. <https://www.ikea.com/us/en/p/tarva-nightstand-pine-50219609/>
- **FÅGELFJÄLLET Nightstand**, dark gray-blue (IKEA) (theme-match): $89.99; W 0.521 x D 0.460 x H 0.660 m. <https://www.ikea.com/us/en/p/fagelfjaellet-nightstand-dark-gray-blue-60633537/>
- **RÅDMANSÖ Nightstand**, brown walnut effect (IKEA): $99.99; W 0.540 x D 0.384 x H 0.581 m. <https://www.ikea.com/us/en/p/radmansoe-nightstand-brown-walnut-effect-80593597/>
- **TONSTAD Nightstand**, oak veneer (IKEA) (theme-match): $149.99; W 0.400 x D 0.400 x H 0.591 m. <https://www.ikea.com/us/en/p/tonstad-nightstand-oak-veneer-80489322/>

### Dressers
- **RAST 6-drawer dresser**, pine (IKEA) (theme-match): $129.99; W 1.241 x D 0.349 x H 0.679 m. <https://www.ikea.com/us/en/p/rast-6-drawer-dresser-pine-00582164/>
- **STORKLINTA 6-drawer dresser**, white (IKEA): $249.99; W 1.400 x D 0.479 x H 0.749 m. <https://www.ikea.com/us/en/p/storklinta-6-drawer-dresser-white-anchor-unlock-function-60561248/>
- **FÅGELFJÄLLET 6-drawer dresser**, dark gray-blue (IKEA) (theme-match): $279.99; W 0.819 x D 0.511 x H 1.229 m. <https://www.ikea.com/us/en/p/fagelfjaellet-6-drawer-dresser-dark-gray-blue-10628246/>
- **ANKARUDDEN 6-drawer dresser**, oak effect (IKEA) (theme-match): $299.99; W 1.384 x D 0.479 x H 0.873 m. <https://www.ikea.com/us/en/p/ankarudden-6-drawer-dresser-with-2-inner-drawers-oak-effect-80598057/>
- **RÅDMANSÖ 6-drawer dresser**, brown walnut effect (IKEA): $349.99; W 1.591 x D 0.479 x H 0.810 m. <https://www.ikea.com/us/en/p/radmansoe-6-drawer-dresser-brown-walnut-effect-40593839/>

### Desks
- **MICKE Desk**, white (IKEA): $109.99; W 1.051 x D 0.498 x H 0.749 m. <https://www.ikea.com/us/en/p/micke-desk-white-80213074/>
- **FJÄLLBO Desk**, black (IKEA): $249.99; W 1.400 x D 0.699 x H 0.749 m. <https://www.ikea.com/us/en/p/fjaellbo-desk-black-90587690/>
- **Nathan James Haley Mid Century Modern Home Office Desk**, Light Brown (Walmart) (theme-match): $261.43; W 1.219 x D 0.610 x H 0.762 m. <https://www.walmart.com/ip/Nathan-James-Haley-Mid-Century-Modern-Home-Office-Desk-Solid-Wood-Writing-Desk-with-Drawer-and-Rounded-Legs-Light-Brown/17548464889>
- **LISABO Desk**, ash veneer (IKEA) (theme-match): $279.99; W 1.280 x D 0.651 x H 0.740 m. <https://www.ikea.com/us/en/p/lisabo-desk-ash-veneer-10606273/>
- **TONSTAD Desk**, oak veneer, 47 1/4" (IKEA) (theme-match): $299.99; W 1.200 x D 0.470 x H 0.749 m. <https://www.ikea.com/us/en/p/tonstad-desk-oak-veneer-60538205/>

### Uncertain or worth knowing
- **Bed heights:** TARVA, BJÖRKSNÄS and TONSTAD-with-storage list no overall "Height", so `height` is their "Headboard height", which is the tallest point. BJÖRKSNÄS also lists "Height 16 7/8"", but that is the frame-side height, not the overall height. MALM's "Height" equals its headboard height.
- **Bed footprint:** BJÖRKSNÄS is 1.721 m wide, slightly over the 1.7 m guideline. It still fits a 3.5 m wall, with about 0.89 m on each side.
- **Walmart dimension order is not labeled.** Both Walmart listings give an unlabeled "Dimensions" value. Renwick's "82.50 x 62.00 x 45.00 in" is read as length x width x height; it is a queen with a 45" headboard. Nathan James Haley's "24.00 x 48.00 x 30.00 in" is read as depth x width x height (a 48" desk at 30" desk height). These are the only plausible readings.
- **Renwick image:** the main image shows the headboard with side wings; the listing title only says "Channel Tufted".
- **FÅGELFJÄLLET style:** both pieces are shaker-style with brass pulls, not strictly scandinavian. They are tagged `theme-match` for their blue color.
- **Third-party Walmart prices** can change often. Both items are sold by Walmart.com and were in stock when checked.
- **Shipping, tax and assembly costs** were not stated on the pages, so they are `null`.
- **Dropped:** IKEA RAMNEFJÄLL queen bed (Kilanda dark blue) because its page gave only package dimensions. Zinus Lottie queen bed (Walmart) because its page gave only height. Target was not used because its product API returned a captcha.

### Change to `catalog_verified.json`
Added `"style.shape": "round"` to `ikea-borgeby-coffee-table-birch-veneer` and `ikea-vittsjo-coffee-table-light-beige-glass`. Both list "Diameter" on their pages, and width equals depth for both (0.699 m and 0.749 m). No other fields were changed. `ikea-tranered-coffee-table-dark-brown` is square (35 3/8" x 35 3/8"), not round, so it was left unchanged.
