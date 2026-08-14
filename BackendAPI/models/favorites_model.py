from db.session import Base
from datetime import datetime
import uuid
from sqlalchemy import Column, String, Text, Boolean,Enum, TIMESTAMP, Float, DateTime,Integer, ARRAY, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from enum import Enum as PyEnum
from sqlalchemy.orm import relationship



class Favorite (Base): 
  __tablename__ = "Favorites"
  __table_args__ = (
      UniqueConstraint('user_id', 'product_id', name='uq_user_product_favorite'),  # F-006 FIX
  )
  id = Column(UUID(as_uuid=True), unique=True, default=uuid.uuid4, primary_key=True, index=True) 
  user_id  = Column(UUID(as_uuid=True),ForeignKey("Users.id"), index=True, nullable=False)
  product_id  = Column(UUID(as_uuid=True),ForeignKey("Products.id"), index=True, nullable=False)
  
  # relationships
  user = relationship("User", back_populates="favorite", lazy="raise_on_sql")
  product = relationship("Product", back_populates="favorite", lazy="raise_on_sql")