"""Build a vehicle <storeData> block from the StoreManager XML schema.

Field names and defaults are the ones registered by
``StoreManager.registerStoreDataXMLPaths`` in
``Documentation/docs/script/Shop/StoreManager.md``:

- ``storeData.name`` is required
- ``storeData.brand`` defaults to ``LIZARD``
- ``storeData.category`` defaults to ``misc``
- ``storeData.price`` defaults to ``10000``
- ``storeData.image`` is marked required by the schema
- ``storeData.bundleElements.bundleElement.configurations.configuration``
  carries ``#name``, ``#value`` and ``#allowChange`` (default false)

``vehicle.washable`` is a separate element registered in
``Documentation/docs/script/Specializations/Washable.md``. It is not a child
of storeData, so it is written beside storeData when requested.

``dataS/storeCategories.xml`` is not in the local documentation, so the only
category name this generator can offer from the schema is the default ``misc``.
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import escape

_ATTRIBUTE_ENTITIES = {'"': "&quot;", "'": "&apos;"}

# The schema's default category. Other names live in storeCategories.xml.
STORE_CATEGORY_DEFAULT = "misc"
STORE_BRAND_DEFAULT = "LIZARD"
STORE_PRICE_DEFAULT = "10000"


@dataclass(frozen=True, slots=True)
class StoreItemRequest:
    """Values collected from the Store Item form."""

    title: str
    brand: str = ""
    price: str = ""
    category: str = STORE_CATEGORY_DEFAULT
    image: str = ""
    washable: bool = False
    configuration_name: str = ""


@dataclass(frozen=True, slots=True)
class GeneratedStoreItem:
    """One well-formed XML document and the suggested file name."""

    xml_text: str
    filename: str = "storeData.xml"


class StoreItemGenerator:
    """Render a storeData document. Does not write a file."""

    @staticmethod
    def generate(request: StoreItemRequest) -> GeneratedStoreItem:
        title = request.title.strip()
        if not title:
            raise ValueError("Item Title is required.")

        category = request.category.strip() or STORE_CATEGORY_DEFAULT
        config_name = request.configuration_name.strip()
        lines = [
            '<?xml version="1.0" encoding="utf-8" standalone="no" ?>',
        ]
        indent = "    " if request.washable else ""
        if request.washable:
            lines.append("<vehicle>")

        lines.append(f"{indent}<storeData>")
        body = indent + "    "
        lines.append(f"{body}<name>{escape(title)}</name>")
        brand = request.brand.strip()
        if brand:
            lines.append(f"{body}<brand>{escape(brand)}</brand>")
        lines.append(f"{body}<category>{escape(category)}</category>")
        price = request.price.strip()
        if price:
            lines.append(f"{body}<price>{escape(price)}</price>")
        image = request.image.strip()
        if image:
            lines.append(f"{body}<image>{escape(image)}</image>")
        if config_name:
            quoted = escape(config_name, _ATTRIBUTE_ENTITIES)
            lines.extend(
                [
                    f"{body}<bundleElements>",
                    f"{body}    <bundleElement>",
                    f"{body}        <configurations>",
                    f'{body}            <configuration name="{quoted}" />',
                    f"{body}        </configurations>",
                    f"{body}    </bundleElement>",
                    f"{body}</bundleElements>",
                ]
            )
        lines.append(f"{indent}</storeData>")
        if request.washable:
            lines.append("    <washable />")
            lines.append("</vehicle>")
        lines.append("")
        return GeneratedStoreItem("\n".join(lines))
