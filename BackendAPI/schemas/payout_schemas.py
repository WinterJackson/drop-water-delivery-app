from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime
from utils.money import MoneyField

class PayoutCreate(BaseModel):
    amount: MoneyField
    payment_method: str
    account_details: str
    idempotency_key: Optional[str] = None

class PayoutResponse(BaseModel):
    id: UUID
    provider_id: UUID
    provider_type: str
    amount: MoneyField
    status: str
    payment_method: str
    account_details: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

class ProviderBalanceResponse(BaseModel):
    lifetime_earnings: MoneyField
    pending_payouts: MoneyField
    completed_payouts: MoneyField
    available_balance: MoneyField
