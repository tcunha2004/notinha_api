import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Every field is optional (None) so the LLM can return PARTIAL data when
# something is illegible, instead of failing validation and losing everything.


class Product(BaseModel):
    """Standardized identity of the item, the same across stores.
    e.g. 'CAFE PILAO 2KG' -> name='Café', brand='Pilão', package_size=2000, package_unit='g'"""

    name: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Generic product name in Portuguese, abbreviations expanded, accents fixed, sentence case. "
            "Include the printed variant (type, flavor, version), "
            "but not the brand, size or packaging. e.g. 'Café', 'Leite integral', 'Açúcar mascavo'"
        ),
    )
    brand: str | None = Field(
        default=None,
        min_length=1,
        description="Brand name, properly spelled and capitalized (e.g. 'Pilão', 'Stevia'). Null if not identifiable",
    )
    package_size: float | None = Field(
        default=None,
        description=(
            "Total net content of ONE sold unit, converted to package_unit "
            "(e.g. 2KG -> 2000, 1,5L -> 1500, 6x350ML -> 2100). Null for items sold by weight"
        ),
    )
    package_unit: Literal["g", "ml", "un"] | None = Field(
        default=None,
        description="Unit of package_size: 'g' for weight, 'ml' for volume, 'un' for count (e.g. 12 eggs)",
    )


class Item(BaseModel):
    """One item line of the invoice"""

    code: str | None = Field(
        default=None, min_length=1, description="Item code ('Código'), as printed"
    )
    raw_description: str | None = Field(
        default=None, min_length=1, description="Item description exactly as printed"
    )
    quantity: float | None = Field(
        default=None, description="Quantity ('Qtde'), e.g. 2 or 0.535"
    )
    unit: str | None = Field(
        default=None, min_length=1, description="Unit of measure ('UN'), e.g. UN, KG, L"
    )
    unit_price: float | None = Field(
        default=None, description="Unit price ('Vl. Unit.')"
    )
    discount: float = Field(default=0.0, description="Item discount, 0 if none")
    total_amount: float | None = Field(
        default=None, description="Line total ('Vl. Total')"
    )

    product: Product | None = Field(
        default=None,
        description="Standardized product interpreted from raw_description",
    )


def _cnpj_check_digit(base: str) -> str:
    # ord(c) - 48 turns '0'-'9' into 0-9 and 'A'-'Z' into 17-42 (alphanumeric CNPJ rule)
    weights = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)[-len(base) :]
    rest = sum((ord(c) - 48) * w for c, w in zip(base, weights)) % 11
    return "0" if rest < 2 else str(11 - rest)


def format_cnpj(value: str) -> str | None:
    """'03821728000172' -> '03.821.728/0001-72'. Accepts the alphanumeric CNPJ too.
    None when length or check digits are wrong (a misread): a wrong CNPJ would create a phantom store."""
    cnpj = re.sub(r"[^0-9A-Z]", "", value.upper())
    if not re.fullmatch(r"[0-9A-Z]{12}[0-9]{2}", cnpj):
        return None
    if cnpj[12] != _cnpj_check_digit(cnpj[:12]) or cnpj[13] != _cnpj_check_digit(cnpj[:13]):
        return None
    return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"


class Store(BaseModel):
    """The store that issued the invoice"""

    name: str | None = Field(
        default=None, min_length=1, description="The legal/corporate name of the store"
    )
    id: str | None = Field(
        default=None,
        min_length=1,
        description="The store CNPJ, formatted as xx.xxx.xxx/xxxx-xx even if printed without punctuation (e.g. 03.821.728/0001-72)",
    )
    address: str | None = Field(
        default=None, min_length=1, description="The address of the store"
    )

    @field_validator("id")
    @classmethod
    def _normalize_cnpj(cls, value: str | None) -> str | None:
        return value and format_cnpj(value)


class Purchase(BaseModel):
    """Purchase totals and payment info"""

    total_amount: float | None = Field(
        default=None, description="Total paid ('Valor a Pagar')"
    )
    payment_method: str | None = Field(
        default=None,
        min_length=1,
        description="Payment method as printed, e.g. Dinheiro, Cartão de Crédito, PIX",
    )
    purchased_at: datetime | None = Field(
        default=None, description="Date and time of the purchase ('Emissão')"
    )


class ExtractionOutput(BaseModel):
    """Analyse the invoice and retrieve the according data"""

    store: Store | None = Field(
        default=None, description="The store that issued the invoice"
    )
    purchase: Purchase | None = Field(
        default=None, description="Purchase totals and payment info"
    )
    items: list[Item] = Field(
        default_factory=list, description="Every item line of the invoice"
    )


class ExtractionResponse(BaseModel):
    """Decide first if the receipt is in scope (invalid). If it is, return the invoice data (full or partial) and whether something required is missing"""

    invalid: bool = Field(
        default=False,
        description=(
            "True when the image is NOT a supermarket/grocery or pharmacy receipt "
            "(e.g. gas station fuel, restaurant/bar/delivery meal, services, parking, or not a receipt at all). "
            "When True, return ONLY this field: missing=false and data=null. False otherwise"
        ),
    )
    missing: bool = Field(
        default=False,
        description=(
            "True when a value printed on the receipt could not be read (illegible, blurred or outside the photo). "
            "Values the receipt doesn't print and 'product' fields don't count. False otherwise"
        ),
    )
    data: ExtractionOutput | None = Field(
        default=None,
        description=(
            "The extracted invoice data, even if partial. "
            "Null when invalid=true or when NO data at all could be read"
        ),
    )
