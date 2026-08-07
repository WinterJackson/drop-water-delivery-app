from sqlalchemy.ext.asyncio import AsyncSession
from models.user_model import User
from schemas.user_schemas import BaseUser

# CREATE USER 
async def createUser( db: AsyncSession , data: BaseUser ):
  user_instance = User(
    clerk_id = data.clerk_id,
    full_name = data.full_name,
    email = data.email,
    phone_number = data.phone_number,
    profile_pic = data.profile_pic,
    # Written here and nowhere else. `pricing_service.welcome_offer_available`
    # refuses the first-order discount when another account on the same handset
    # has already taken it; a client that could update this field could reset
    # that check by sending a new value.
    device_id = (data.device_id or None),
  )
  db.add(user_instance)
  await db.commit()
  await db.refresh(user_instance)
  return user_instance


# check if user exists