from pydantic import BaseModel, Field


class ItemIn(BaseModel):
    """What the user can correct. The line total is always recomputed from these."""

    description: str = Field(min_length=1, max_length=200)
    quantity: float = Field(gt=0, le=100_000)
    unit: str = Field(min_length=1, max_length=10)
    unit_price: float = Field(ge=0, le=1_000_000)
    discount: float = Field(default=0, ge=0, le=1_000_000)

    def values(self) -> tuple:
        total = max(0.0, round(self.quantity * self.unit_price - self.discount, 2))
        return (
            self.description.strip(),
            self.quantity,
            self.unit,
            self.unit_price,
            self.discount,
            total,
        )


class PurchaseIn(BaseModel):
    """The receipt total ("Valor a pagar"), e.g. when it was cut off in the photo."""

    total_amount: float = Field(ge=0, le=1_000_000)
