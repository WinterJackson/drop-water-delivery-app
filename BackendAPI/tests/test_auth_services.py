import pytest
from unittest.mock import AsyncMock, MagicMock
from schemas.deliverer_schemas import CreateDeliverer
from schemas.vendor_schemas import CreateVendor

class TestAuthServices:
    @pytest.mark.asyncio
    async def test_get_existing_rider(self):
        """Test getting rider by clerk_id."""
        from services.rider_auth_service import get_existing_rider
        
        db = AsyncMock()
        mock_result = MagicMock()
        mock_rider = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_rider
        db.execute.return_value = mock_result
        
        result = await get_existing_rider("clerk_123", db)
        assert result == mock_rider
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_rider(self):
        """Test creating a new rider."""
        from services.rider_auth_service import create_rider
        
        db = AsyncMock()
        db.add = MagicMock()
        data = CreateDeliverer(
            clerk_id="clerk_123",
            email="test@rider.com",
            name="Test Rider",
            phone_number="254712345678",
            vehicle_type="motorbike",
            plate_number="KAA 123A",
            ID_number="12345678"
        )
        
        result = await create_rider(db, data)
        assert result.clerk_id == "clerk_123"
        assert result.is_active is False
        db.add.assert_called_once()
        db.commit.assert_called_once()
        db.refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_existing_vendor(self):
        """The caller's own store, resolved so a second one cannot break it.

        This used to assert `scalar_one_or_none()`, which raises
        `MultipleResultsFound` the moment an owner opens a branch — and this
        function backs `POST /api/auth/create_vendor`, the endpoint the vendor
        app's onboarding posts to, so that was a 500 from the one screen a
        vendor cannot get past. `.scalars().first()` over an ordered, limited
        query is what a multi-store owner needs.
        """
        from services.vendor_auth_service import get_existing_vendor

        db = AsyncMock()
        mock_result = MagicMock()
        mock_vendor = MagicMock()
        mock_result.scalars.return_value.first.return_value = mock_vendor
        db.execute.return_value = mock_result

        result = await get_existing_vendor("clerk_456", db)
        assert result == mock_vendor
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_vendor(self):
        """Test creating a new vendor."""
        from services.vendor_auth_service import create_vendor
        
        db = AsyncMock()
        db.add = MagicMock()
        data = CreateVendor(
            clerk_id="clerk_456",
            email="vendor@test.com",
            owners_name="Vendor Owner",
            business_name="Water Shop",
            phone_number="254798765432",
            vendor_type="retail_refill",
            business_license="LIC123",
            profile_pic="pic.jpg",
            location_address="CBD",
            lat=1.2,
            lng=36.8
        )
        
        result = await create_vendor(db, data)
        assert result.clerk_id == "clerk_456"
        assert result.verification_status == "pending"
        db.add.assert_called_once()
        db.commit.assert_called_once()
        db.refresh.assert_called_once()
