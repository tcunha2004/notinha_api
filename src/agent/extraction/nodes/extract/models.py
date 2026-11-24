from datetime import datetime

from pydantic import BaseModel, Field


class Item(BaseModel):
    """One product line of the invoice"""

    raw_description: str = Field(min_length=1, description="Item description exactly as printed")
    code: str = Field(min_length=1, description="Item code ('Código'), as printed")
    quantity: float = Field(description="Quantity ('Qtde'), e.g. 2 or 0.535")
    unit: str = Field(min_length=1, description="Unit of measure ('UN'), e.g. UN, KG, L")
    unit_price: float = Field(description="Unit price ('Vl. Unit.')")
    discount: float = Field(default=0.0, description="Item discount, 0 if none")
    total_amount: float = Field(description="Line total ('Vl. Total')")


class Store(BaseModel):
    """The store that issued the invoice"""

    name: str = Field(min_length=1, description="The legal/corporate name of the store")
    id: str = Field(min_length=1, description="The ID of the store (e.g.: CNPJ)")
    address: str = Field(min_length=1, description="The address of the store")


class Purchase(BaseModel):
    """Purchase totals and payment info"""

    total_amount: float = Field(description="Total paid ('Valor a Pagar')")
    payment_method: str = Field(
        min_length=1,
        description="Payment method as printed, e.g. Dinheiro, Cartão de Crédito, PIX"
    )
    purchased_at: datetime = Field(
        description="Date and time of the purchase ('Emissão')"
    )


class ExtractionOutput(BaseModel):
    """Analyse the invoice and retrieve the according data"""

    store: Store = Field(description="The store that issued the invoice")
    purchase: Purchase = Field(description="Purchase totals and payment info")
    items: list[Item] = Field(min_length=1, description="Every product line of the invoice")


class ExtractionResponse(BaseModel):
    """Either the full invoice data, or an error explaining why it couldn't be extracted"""

    error: str | None = Field(
        default=None,
        description="Set ONLY when a required field is illegible or missing, naming which ones. Null otherwise",
    )
    data: ExtractionOutput | None = Field(
        default=None, description="The extracted invoice data. Null when error is set"
    )
