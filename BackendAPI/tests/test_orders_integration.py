import pytest
import respx
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
from main import app
from utils.verify_user_token import get_current_user

class TestOrdersIntegration:
    @pytest.mark.asyncio
    @patch("routes.cart_routes.add_to_cart_service", new_callable=AsyncMock)
    @patch("routes.cart_routes.get_user", new_callable=AsyncMock)
    async def test_add_to_cart_route(self, mock_get_user, mock_add_service, client: httpx.AsyncClient):
        """Test adding item to cart through HTTP endpoint."""
        mock_add_service.return_value = {"message": "Item added successfully."}
        mock_user = MagicMock()
        mock_user.id = "user-1"
        mock_get_user.return_value = mock_user
        
        # Override dependency or mock decoded_token inside the route
        app.dependency_overrides[get_current_user] = lambda: {"sub": "test_sub", "user_id": "test_user_1"}
        response = await client.post(
            "/api/cart/add_to_cart",
            json={"id": "123e4567-e89b-12d3-a456-426614174000", "quantity": 2, "user_id": "", "force_replace": False},
            headers={"Authorization": "Bearer test_token"}
        )
        
        assert response.status_code == 200
        assert response.json() == {"message": "Item added to cart"}
        mock_add_service.assert_called_once()

    @pytest.mark.asyncio
    @patch("routes.cart_routes.fetch_cart", new_callable=AsyncMock)
    @patch("routes.cart_routes.get_user", new_callable=AsyncMock)
    async def test_get_cart_route(self, mock_get_user, mock_fetch_cart, client: httpx.AsyncClient):
        """Test fetching cart contents."""
        mock_fetch_cart.return_value = [{"product_id": 1, "quantity": 2}]
        mock_user = MagicMock()
        mock_user.id = "user-1"
        mock_get_user.return_value = mock_user
        
        app.dependency_overrides[get_current_user] = lambda: {"sub": "test_sub", "user_id": "test_user_1"}
        response = await client.get(
            "/api/cart/get_cart",
            headers={"Authorization": "Bearer test_token"}
        )
        
        assert response.status_code == 200
        assert len(response.json()) == 1

    @pytest.mark.asyncio
    @patch("routes.cart_routes.get_user", new_callable=AsyncMock)
    @patch("services.cart_services.fetch_detailed_cart", new_callable=AsyncMock)
    async def test_checkout_rejects_empty_cart(self, mock_detailed_cart, mock_get_user, client: httpx.AsyncClient):
        """An empty cart must be a clean 400, not a 500.

        `mpesa_payment` used to null-guard the cart for the lock check and then
        dereference it unconditionally two lines later, so checking out with no
        cart produced an AttributeError and a generic "Internal server error".
        """
        mock_user = MagicMock()
        mock_user.id = uuid4()
        mock_get_user.return_value = mock_user
        mock_detailed_cart.return_value = None

        app.dependency_overrides[get_current_user] = lambda: {"sub": "test_sub"}
        response = await client.post(
            "/api/cart/mpesa_payment",
            json={
                "phone": "254700000000",
                "id": str(uuid4()),
                "lat": -1.28,
                "lng": 36.82,
                "delivery_type": "quick_swap",
            },
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    @patch("routes.cart_routes.get_user", new_callable=AsyncMock)
    async def test_checkout_rejects_malformed_phone(self, mock_get_user, client: httpx.AsyncClient):
        """A bad MSISDN is rejected before any pricing or STK work happens."""
        mock_user = MagicMock()
        mock_user.id = uuid4()
        mock_get_user.return_value = mock_user

        app.dependency_overrides[get_current_user] = lambda: {"sub": "test_sub"}
        response = await client.post(
            "/api/cart/mpesa_payment",
            json={
                "phone": "0700000000",  # missing 254 country code
                "id": str(uuid4()),
                "lat": -1.28,
                "lng": 36.82,
            },
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == 400
        assert "2547" in response.json()["detail"]

    @pytest.mark.asyncio
    @patch("routes.cart_routes.initiate_stk_push", new_callable=AsyncMock)
    @patch("routes.cart_routes.create_order", new_callable=AsyncMock)
    @patch("routes.cart_routes._load_priced_cart", new_callable=AsyncMock)
    @patch("routes.cart_routes.get_user", new_callable=AsyncMock)
    async def test_checkout_charges_exactly_what_it_records(
        self, mock_get_user, mock_load_priced_cart, mock_create_order, mock_stk_push,
        client: httpx.AsyncClient, db_session,
    ):
        """The regression guard for the whole class of bugs B1–B3.

        The route must push the quote's amount to M-Pesa and hand that *same*
        quote object to `create_order`, so the amount charged and the amount
        recorded on the order cannot diverge. Previously the route computed its own
        total (retail service fee 10, no surge) while `create_order` computed
        another (service fee 12, plus surge), which made the callback's amount
        cross-check reject every retail payment.
        """
        from services.pricing_service import OrderQuote
        from decimal import Decimal

        cart_id = uuid4()
        cart_item = MagicMock()
        cart_item.quantity = 2
        cart_item.product.stock = 50
        cart_item.product.name = "Dasani 20L"
        # On sale and not withdrawn — a bare MagicMock is neither.
        cart_item.product.deleted_at = None
        cart_item.product.is_available = True

        cart = MagicMock()
        cart.id = cart_id
        cart.is_locked = False
        cart.cart_item = [cart_item]

        quote = OrderQuote(
            vendor_id=uuid4(), vendor_type="retail_refill", delivery_type="quick_swap",
            total_quantity=2, total_weight_kg=Decimal("40.00"), vehicle_class="motorbike",
            distance_km=1.2, estimated_minutes=5, lat_from=-1.28, lng_from=36.82,
            product_subtotal=Decimal("500.00"), delivery_fee=Decimal("68.00"),
            service_fee=Decimal("12.00"), surge_fee=Decimal("10.00"),
            delivery_markup=Decimal("0.00"), payload_surcharge=Decimal("0.00"),
            staircase_surcharge=Decimal("0.00"),
            bottle_deposit=Decimal("0.00"),
            debt_settlement=Decimal("0.00"),
            welcome_discount=Decimal("0.00"),
            mpesa_discount=Decimal('0.00'), wallet_discount=Decimal("0.00"),
            rounding_adjustment=Decimal("0.00"),
            total=Decimal("590"), surge_active=True, is_welcome_offer=False,
            revenue={
                "vendor_commission": 25.0, "service_fee": 12.0, "rider_commission": 6.8,
                "platform_total": 53.8, "vendor_net": 475.0, "rider_net": 61.2,
                "surge_fee": 10.0, "delivery_markup": 0.0,
                "platform_cost": 15.0, "platform_net": 45.0,
            },
        )

        mock_user = MagicMock()
        mock_user.id = uuid4()
        mock_user.debt_balance = 0
        mock_user.wallet_balance = 0
        mock_get_user.return_value = mock_user
        mock_load_priced_cart.return_value = (cart, mock_user, MagicMock(), quote)
        mock_stk_push.return_value = {"CheckoutRequestID": "ws_CO_TEST"}

        created = MagicMock()
        created.id = uuid4()
        mock_create_order.return_value = created

        app.dependency_overrides[get_current_user] = lambda: {"sub": "test_sub"}
        response = await client.post(
            "/api/cart/mpesa_payment",
            json={
                "phone": "254700000000",
                "id": str(cart_id),
                "lat": -1.28,
                "lng": 36.82,
                "delivery_type": "quick_swap",
            },
            headers={"Authorization": "Bearer test_token"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["CheckoutRequestID"] == "ws_CO_TEST"

        # 1. M-Pesa was asked for exactly the quoted total, as a whole number.
        stk_amount = mock_stk_push.await_args.kwargs["amount"]
        assert stk_amount == 590
        assert isinstance(stk_amount, int)

        # 2. The order was created from that identical quote — not re-priced.
        assert mock_create_order.await_args.kwargs["quote"] is quote

        # 3. And the amount reported back to the client agrees too — as a
        #    decimal *string*, like every money field this API returns.
        assert body["amount"] == "590.00"
