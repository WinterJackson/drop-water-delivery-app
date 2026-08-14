from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from services.vendor_service import get_all_vendors, get_nearby_vendors, get_top_rated_vendors, get_vendor_by_id_service, get_vendors_by_type_service, get_top_brands_service
from services.user_service import get_user_coordinates
from schemas.vendor_schemas import VendorWithProductsThin, BaseVendor, VendorWithProductsFull, RequestBodyVendorId, VendorType
from dependencies.dependencies import get_db
from dependencies.auth_dependencies import get_current_customer
from core.redis_client import cache_get, cache_set

router = APIRouter()
# GET ALL VENDORS 
@router.get("/vendors")
async def fetch_all_vendors(session: AsyncSession = Depends(get_db), limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
  cache_key = f"all_vendors_{limit}_{offset}"
  cached_response = await cache_get(cache_key)
  if cached_response:
      return cached_response

  vendors, total = await get_all_vendors(session, limit, offset)
  response_data = {"data": [BaseVendor.model_validate(v).model_dump() for v in vendors], "total": total, "limit": limit, "offset": offset}
  
  await cache_set(cache_key, response_data, ttl_seconds=300) # 5 min cache
  return response_data

# GET NEARBY VENDORS FOR QUICK REFILLS
@router.get("/nearby_vendors") # Removed response_model to return dict directly for cache compatibility
async def fetch_nearby_vendors(db: AsyncSession = Depends(get_db),user = Depends(get_current_customer)):
  clerk_id = user["sub"]
  coords = await get_user_coordinates(session=db, clerk_id=clerk_id)
  if not coords or not coords.lat or not coords.lng:
      return []
  
  cache_key = f"nearby_vendors_{clerk_id}"
  cached = await cache_get(cache_key)
  if cached:
      return cached

  vendors = await get_nearby_vendors(session=db, lat=coords.lat, lng=coords.lng)
  # Serialize manually because we dropped response_model for caching
  result = [VendorWithProductsThin.model_validate(v).model_dump() for v in vendors]
  
  await cache_set(cache_key, result, ttl_seconds=120)
  return result

# GET THE TOP RATED VENDOR NEAR YOU
@router.get("/top_rated_vendors", response_model=list[BaseVendor])
async def top_rated_vendors( db: AsyncSession = Depends(get_db), user = Depends(get_current_customer)):
  clerk_id = user["sub"]
  coords = await get_user_coordinates(session=db, clerk_id=clerk_id)
  if not coords or not coords.lat or not coords.lng:
      return []
  vendors = await get_top_rated_vendors(session=db, lat=coords.lat, lng=coords.lng)
  return vendors

# GET VENDOR BY ID FOR THE VENDOR PROFILE 
@router.post("/vendor_details_and_products", response_model= VendorWithProductsFull)
async def get_vendor_by_id(request_body: RequestBodyVendorId, db : AsyncSession = Depends(get_db) ):
  vendor = await get_vendor_by_id_service(session=db, id=request_body.id)
  if not vendor:
    raise HTTPException(status_code=404, detail="Vendor details Do not exist")
  return vendor

# GET VENDOR BY TYPE 
@router.post("/vendor_by_type", response_model=list[BaseVendor])
async def get_vendors_by_type(request_body: VendorType, db : AsyncSession = Depends(get_db), user = Depends(get_current_customer) ):
  # get coordinates from the database  
  clerk_id = user["sub"]
  coords = await get_user_coordinates(session=db, clerk_id=clerk_id)
  if not coords or not coords.lat or not coords.lng:
      return []
  vendors = await get_vendors_by_type_service(session=db, type=request_body.vendor_type, lng=coords.lng, lat=coords.lat)
  return vendors

#  GET VENDORS OF TOP BRANDS AND THAT ARE NEAR YOUR OF TYPE WHOLE_SELLER 
@router.get("/get_top_brands", response_model=list[BaseVendor])
async def get_top_brands(db : AsyncSession = Depends(get_db), user = Depends(get_current_customer)):
  clerk_id = user["sub"]
  coords = await get_user_coordinates(session=db, clerk_id=clerk_id)
  if not coords or not coords.lat or not coords.lng:
    return []
  
  vendors = await get_top_brands_service(session=db, lat=coords.lat, lng=coords.lng)
  return vendors

# GET VENDOR DIRECTORY (ALL VENDORS BY DISTANCE)
@router.get("/vendors/directory", response_model=list[VendorWithProductsThin])
async def fetch_vendor_directory(
    db: AsyncSession = Depends(get_db), 
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search_query: Optional[str] = Query(None),
    vendor_type: Optional[str] = Query("all"),
    user = Depends(get_current_customer)
):
  from services.vendor_service import get_vendor_directory
  clerk_id = user["sub"]
  coords = await get_user_coordinates(session=db, clerk_id=clerk_id)
  if not coords or not coords.lat or not coords.lng:
      return []
  vendors = await get_vendor_directory(
      session=db,
      lat=coords.lat,
      lng=coords.lng,
      limit=limit,
      offset=offset,
      search_query=search_query,
      vendor_type=vendor_type
  )
  return vendors