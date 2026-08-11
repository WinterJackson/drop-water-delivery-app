import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Numeric, TIMESTAMP, func, Index, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from enum import Enum as PyEnum
from db.session import Base

class UserType(str, PyEnum):
    customer = "customer"
    vendor = "vendor"
    rider = "rider"

class TransactionType(str, PyEnum):
    top_up = "top_up"
    withdrawal = "withdrawal"
    order_payment = "order_payment"
    commission_deduction = "commission_deduction"
    refund = "refund"

class TransactionStatus(str, PyEnum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"

class WalletTransaction(Base):
    __tablename__ = "WalletTransactions"
    __table_args__ = (
        Index('idx_wallet_trans_user_type_id', 'user_type', 'user_id'),
        Index('idx_wallet_trans_status', 'status'),
        Index('idx_wallet_trans_mpesa_receipt', 'mpesa_receipt_number'),
        Index('idx_wallet_trans_owner', 'wallet_owner_id'),
    )

    id = Column(UUID(as_uuid=True), unique=True, primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(String, nullable=False, index=True)
    user_type = Column(SQLEnum(UserType, name="wallet_user_type", create_type=False), nullable=False)

    #: The balance row this movement belongs to — `Vendors.id`, `Deliverers.id`
    #: or `Users.id`. No foreign key, for the same reason `user_id` has none: it
    #: points into one of three tables.
    #:
    #: `user_id` is a Clerk id, and one identity may own several stores, each
    #: with its own `wallet_balance`. Callbacks arrive minutes later and used to
    #: re-resolve the owner by clerk id with `.first()`, so a top-up paid into
    #: the second branch credited the first and a failed withdrawal from the
    #: second was refunded to the first. Nullable: rows written before this
    #: column existed fall back to the clerk-id lookup.
    wallet_owner_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    transaction_type = Column(SQLEnum(TransactionType, name="wallet_transaction_type", create_type=False), nullable=False)
    
    amount = Column(Numeric(10, 2), nullable=False)
    status = Column(SQLEnum(TransactionStatus, name="wallet_transaction_status", create_type=False), nullable=False, default=TransactionStatus.pending)
    
    # E.g. CheckoutRequestID for STK Push, ConversationID for B2C, or the actual receipt ID after callback
    reference_id = Column(String, nullable=True, index=True)
    mpesa_receipt_number = Column(String, nullable=True, index=True)
    
    description = Column(String, nullable=True)
    failure_reason = Column(String, nullable=True)
    
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

