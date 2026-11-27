from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator

# Stripped before the length check, so "   " is rejected instead of saved as "".
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class NewProductIn(BaseModel):
    """A product the user creates in the edit sheet. Same columns as the products table."""

    name: Text
    brand: Text | None = None
    # Both or neither: None for items sold by weight/volume (bananas, bread by the kg).
    package_size: float | None = Field(default=None, gt=0, le=1_000_000)
    package_unit: Literal["g", "ml", "un"] | None = None

    @model_validator(mode="after")
    def size_needs_unit(self) -> Self:
        if (self.package_size is None) != (self.package_unit is None):
            raise ValueError("package_size and package_unit go together")
        return self


class ItemIn(BaseModel):
    """What the user can correct. The line total is always recomputed from these."""

    # The product picked in the edit sheet; None leaves the item unidentified.
    product_id: UUID | None = None
    # "Criar novo produto": created on save (or the identical one found) and linked; wins over product_id.
    new_product: NewProductIn | None = None
    quantity: float = Field(gt=0, le=100_000)
    unit: str = Field(min_length=1, max_length=10)
    unit_price: float = Field(ge=0, le=1_000_000)
    discount: float = Field(default=0, ge=0, le=1_000_000)

    def values(self) -> tuple:
        total = max(0.0, round(self.quantity * self.unit_price - self.discount, 2))
        return (self.quantity, self.unit, self.unit_price, self.discount, total)


class PurchaseIn(BaseModel):
    """The receipt total ("Valor a pagar"), e.g. when it was cut off in the photo."""

    total_amount: float = Field(ge=0, le=1_000_000)
