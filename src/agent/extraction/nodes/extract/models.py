from datetime import datetime

from pydantic import BaseModel, Field

# Every field is optional (None) so the LLM can return PARTIAL data when
# something is illegible, instead of failing validation and losing everything.


class Item(BaseModel):
    """One product line of the invoice"""

    raw_description: str | None = Field(
        default=None, min_length=1, description="Item description exactly as printed"
    )
    code: str | None = Field(
        default=None, min_length=1, description="Item code ('Código'), as printed"
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


class Store(BaseModel):
    """The store that issued the invoice"""

    name: str | None = Field(
        default=None, min_length=1, description="The legal/corporate name of the store"
    )
    id: str | None = Field(
        default=None,
        min_length=1,
        description="The ID of the store (CNPJ). MUST be in the format xx.xxx.xxx/xxxx-xx (e.g. 03.821.728/0001-72, 20.184.393/0001-70)",
    )
    address: str | None = Field(
        default=None, min_length=1, description="The address of the store"
    )


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
        default_factory=list, description="Every product line of the invoice"
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
        description="True when ANY field is illegible, cut off or absent. False otherwise",
    )
    data: ExtractionOutput | None = Field(
        default=None,
        description=(
            "The extracted invoice data, even if partial. "
            "Null when invalid=true or when NO data at all could be read"
        ),
    )
