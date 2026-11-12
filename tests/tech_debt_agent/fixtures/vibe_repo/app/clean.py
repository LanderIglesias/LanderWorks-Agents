from dataclasses import dataclass


@dataclass(frozen=True)
class Invoice:
    net_amount: float
    tax_rate: float


def tax_amount(invoice: Invoice) -> float:
    return invoice.net_amount * invoice.tax_rate


def total_amount(invoice: Invoice) -> float:
    return invoice.net_amount + tax_amount(invoice)


def apply_discount(amount: float, percent: float) -> float:
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    return amount * (1 - percent / 100)
