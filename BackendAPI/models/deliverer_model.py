from db.session import Base
from datetime import datetime, time, timezone
import uuid
from sqlalchemy import Column, String, Text, Boolean, TIMESTAMP, Float, Numeric, Time, func, Index, Enum, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from enum import Enum as PyEnum
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography
from sqlalchemy_utils import StringEncryptedType
from sqlalchemy_utils.types.encrypted.encrypted_type import AesEngine
from utils.encryption import DB_ENCRYPTION_KEY
class RiderVehicleType(str, PyEnum):
    motorbike = "motorbike"
    tuktuk = "tuktuk"
    truck = "truck"

class RiderEmploymentType(str, PyEnum):
    gig_economy = "gig_economy"
    in_house = "in_house"

class KYCStatus(str, PyEnum):
    unsubmitted = "unsubmitted"
    pending = "pending"
    approved = "approved"
    rejected = "rejected"

class Deliverer(Base):
  __tablename__ = "Deliverers"
  __table_args__ = (
      Index('idx_deliverer_location_gist', 'location', postgresql_using='gist'),
  )
  id = Column(UUID(as_uuid=True), unique=True, primary_key=True, default=uuid.uuid4, index=True)
  clerk_id = Column(String, nullable=True, unique=True, index=True)
  name = Column(String, index=True, nullable=False)
  email = Column(String, unique=True, index=True, nullable=False) 
  phone_number = Column(String, index=True, nullable=True)  #will revisit 
  profile_pic = Column(Text, nullable=True)
  driver_license = Column(Text, nullable=True)
  ID_number = Column(StringEncryptedType(String, DB_ENCRYPTION_KEY, AesEngine, 'pkcs5'), nullable=False)
  vehicle_type = Column(Enum(RiderVehicleType, name="rider_vehicle_type", create_type=False), nullable=False, default=RiderVehicleType.motorbike, index=True)
  employment_model = Column(Enum(RiderEmploymentType, name="rider_employment_type", create_type=False), nullable=False, default=RiderEmploymentType.gig_economy, index=True)
  employer_vendor_id = Column(UUID(as_uuid=True), ForeignKey("Vendors.id", ondelete="SET NULL"), nullable=True, index=True)

  plate_number = Column(String, nullable=True, index=True)
  id_card_front = Column(Text, nullable=True)
  id_card_back = Column(Text, nullable=True)
  kyc_status = Column(Enum(KYCStatus, name="deliverer_kyc_status", create_type=False), nullable=False, default=KYCStatus.unsubmitted, index=True)
  #: Why the last review was rejected, shown on `VerificationWall`.
  #:
  #: The reason used to exist only inside the push notification the reviewer
  #: triggered. A rider who dismissed it — or never received it — went back to a
  #: form that prefills their previous answers and offers no clue what was wrong
  #: with them, so the usual outcome was resubmitting the same document. Cleared
  #: on the next submission so a stale reason cannot outlive the problem.
  kyc_rejection_reason = Column(Text, nullable=True)
  kyc_reviewed_at = Column(TIMESTAMP(timezone=True), nullable=True)
  
  current_lat = Column(Float, nullable=True , index=True)
  current_lng = Column(Float, nullable=True , index=True)
  operation_lat = Column(Float, nullable=True)
  operation_lng = Column(Float, nullable=True)
  preferences = Column(JSONB, nullable=True)
  payment_methods = Column(JSONB, nullable=True)
  zone_changes_this_month = Column(Integer, default=0, nullable=False)
  last_zone_change = Column(TIMESTAMP(timezone=True), nullable=True)
  location = Column(Geography(geometry_type="POINT", srid=4326))
  h3_index_res8 = Column(String(16), nullable=True, index=True)
  is_available = Column(Boolean, default=True, index=True)
  is_active = Column(Boolean, default=False, index=True)

  # ── Suspension, set by an administrator ───────────────────────────────
  #: Distinct from `kyc_status` and from `is_active`. A rider can be fully
  #: verified and still need to be stopped today; rejecting their KYC to
  #: achieve that would misrepresent why, and re-approving would lose the
  #: original review.
  suspended_at = Column(TIMESTAMP(timezone=True), nullable=True)
  suspension_reason = Column(Text, nullable=True)
  suspended_by = Column(UUID(as_uuid=True), nullable=True)
  is_verified = Column(Boolean, default=False, index=True)
  is_platinum = Column(Boolean, default=False, index=True)  # Gamification tier (drops commission to 7%)
  # `rating` is the derived average. `rating_count`/`rating_sum` are what it is
  # derived *from*, maintained incrementally by `review_service` so submitting a
  # review costs one row update instead of an AVG over every review the target
  # has ever received. `rating_count` is also what the apps need to render
  # "4.8 (312)" — an average alone cannot distinguish one perfect review from
  # three hundred.
  rating = Column(Float, default=5.0, index=True)
  rating_count = Column(Integer, nullable=False, server_default='0')
  rating_sum = Column(Float, nullable=False, server_default='0')
  acceptance_rate = Column(Float, default=100.0)
  # Numeric, never Float: this is money. Float arithmetic on balances drifts,
  # and this column now gates both cash-order float and payout availability.
  wallet_balance = Column(Numeric(10, 2), default=0, nullable=False, index=True)
  shift_start = Column(Time, default=time(7,0), nullable=False, index=True)
  shift_end = Column(Time, default=time(19,0), nullable=False, index=True)
  push_token = Column(String(255), nullable=True)
  created_at= Column(TIMESTAMP(timezone=True), server_default=func.now())
  updated_at= Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
  
  # relationships
  order = relationship("Order", back_populates="deliverer", lazy="raise_on_sql")

  @property
  def is_suspended(self) -> bool:
      """Stopped by an administrator.

      Reads `suspended_at` and deliberately **not** `is_active`. Suspension
      writes both, so either would answer correctly for a suspended rider — but
      `is_active` is overloaded: `create_deliverer` defaults it to `False`, so
      it also means "has not finished onboarding". Testing it here would tell a
      half-registered rider their account was suspended, which is untrue and
      unactionable. `suspended_at` means one thing and is written by one place.
      """
      return self.suspended_at is not None

def dispatchable_rider():
    """The predicate for a rider the platform may offer work to.

    Every rider search on the dispatch path filtered on `is_available` and
    nothing else about the rider's standing. `is_available` is the rider's own
    toggle — it says they are online, not that the platform still wants them
    working — so the three radar searches offered orders to riders an
    administrator had suspended and to riders whose KYC was `pending`,
    `unsubmitted` or explicitly `rejected`.

    The route gates caught half of that: `get_verified_rider` refuses an
    unapproved KYC at `POST /orders/{id}/accept`. Nothing refused a *suspended*
    rider anywhere, so a suspension amounted to a toggle the rider could undo —
    and the unapproved riders were still pushed the pickup address and the
    customer's area for an order they could never take, while occupying slots in
    a fan-out that is deliberately bounded (`RADAR_FANOUT_LIMIT`).

    Spread into a query as `.where(*dispatchable_rider())`.

    `is_active` is deliberately absent: it is overloaded — `create_deliverer`
    defaults it to `False`, so it means "has not finished onboarding" as well as
    "suspended". Filtering on it here would silently drop riders whose only
    fault is a lifecycle flag, on the query that decides whether an order gets
    delivered at all. `suspended_at` is written by exactly one place and means
    exactly one thing.
    """
    return (
        Deliverer.is_available.is_(True),
        Deliverer.suspended_at.is_(None),
        Deliverer.kyc_status == KYCStatus.approved,
    )
