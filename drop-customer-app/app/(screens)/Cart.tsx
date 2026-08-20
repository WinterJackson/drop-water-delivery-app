// export const unstable_settings = {
//   animation: "slide_from_right",
// };

import {
    View,
    Image,
    ScrollView,
    Dimensions,
    StatusBar,
    ImageBackground,
    Modal,
    StyleSheet,
    ActivityIndicator,
} from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import React, { useContext, useEffect, useState, useRef, useCallback, useMemo } from "react";
import { BRAND } from "@/constants/brandColors";
import { randomUUID } from 'expo-crypto';
//   import { StatusBar } from "expo-status-bar";
import BackButton from "@/components/ui/BackButton";
import CartItem from "@/components/common/CartItem";
import { CartItemSkeleton } from "@/components/skeletons/ContextualSkeletons";
import { EmptyState } from "@/components/ui/EmptyState";
import Button from "@/components/ui/Button";
import { useRouter } from "expo-router";
import Animated, {
	useSharedValue,
	useAnimatedStyle,
	withTiming,
} from "react-native-reanimated";
import { SafeAreaView } from "react-native-safe-area-context";
import { LinearGradient } from "expo-linear-gradient";
import { UIThemeContext } from "@/context/ThemeContext";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { useAuth } from "@clerk/clerk-expo";
import images from "@/constants/images/images";
import Context from "@/context/context";

import { ROUTES } from "@/API/routes/ApiRoutes";
import { ApiError, errorMessage } from "@/API/errors";
import { useApiRequest } from "@/API/useApiClient";
import { Toast } from "@/lib/toast";
import { useUserDetails } from "@/hooks/queries/useUser";
import { useDetailedCart, useDeliveryFee, useCartQuote } from "@/hooks/queries/useCart";
import { RefreshControl } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { DataFallbackUI } from "@/components/ui/DataFallbackUI";
import PressableScale from "@/components/ui/PressableScale";
import { compareMoney, formatMoney, formatMoneyShort, isNegativeMoney, isZeroMoney, subtractMoney } from "@/utils/money";

const { width, height } = Dimensions.get("screen");

/**
 * M-Pesa result codes that are final. Continuing to poll after one of these is
 * pure noise — the customer has already cancelled, timed out, or failed the PIN.
 */
const TERMINAL_MPESA_CODES = new Set(["1", "1032", "1037", "2001"]);

/** Widening poll schedule, in milliseconds. */
const POLL_INTERVALS_MS = [3000, 3000, 5000, 5000, 8000];
const POLL_CEILING_MS = 90_000;

export default function Cart() {
	// <--------------HOOKS---------------->
	const router = useRouter();
	const { fetchCart } = useContext(Context)
	const { data: User } = useUserDetails()
	const {currentTheme} = useContext(UIThemeContext);
	const darkTheme = currentTheme === "dark"
	const api = useApiRequest()
	/**
	 * Three distinct transactions, not two.
	 *
	 * `exchange` — a pool bottle for the pool bottle you hand back.
	 * `refill_mine` — **your** bottle, collected, refilled and returned. The
	 *   hygiene option: nobody else's kitchen. A round trip, so it costs more.
	 * `new_bottle` — the platform's bottle, and you keep it. The only one that
	 *   takes a deposit.
	 *
	 * "Keep My Bottle" used to mean the last of those while being named for the
	 * middle one, so a household that wanted their own bottle refilled was
	 * charged a KSH 300 deposit on a bottle they already owned.
	 */
	type BottleOption = 'exchange' | 'refill_mine' | 'new_bottle';
	const [deliveryType, setDeliveryType] = useState<BottleOption>('exchange');
	
	// <--------------REACT QUERY-------------->
	// Declared before the quote because the quote depends on it: the total
	// differs by `mpesa_payment_discount` depending on how the customer pays.
	const [PaymentMethod, setPaymentMethod] = useState<string | null>(null); // "mpesa" | "cash"

	const { data: Cart, isLoading: isCartLoading, refetch: refetchCart, isRefetching } = useDetailedCart();

	const total_quantity = Cart?.total_quantity ?? Cart?.cart_item?.reduce((acc: number, item: any) => acc + item.quantity, 0) ?? 0;
	const vendor_type = Cart?.vendor_type || 'retail_refill';

	/**
	 * The price shown to the customer is computed by the server and rendered
	 * verbatim. This screen used to re-derive the whole total locally — service
	 * fee, deposit, welcome discount, surcharges, wallet credit — and its formula
	 * disagreed with both the amount M-Pesa charged and the amount written to the
	 * order. Every figure below now comes from one place.
	 */
	const {
		data: quote,
		isLoading: isQuoteLoading,
		error: quoteError,
		refetch: refetchQuote,
	} = useCartQuote(
		User?.lat,
		User?.lng,
		deliveryType,
		!!Cart?.cart_item?.length,
		// The chosen method, not a fixed "mpesa". `mpesa_payment_discount` comes
		// off when the customer is not paying cash, and the server defaults this
		// to "mpesa" — so quoting without it showed every basket the discounted
		// figure and then charged a cash order the undiscounted one.
		PaymentMethod ?? "mpesa",
	);

	// Per-option fees, used only to label the delivery-type selector.
	const { data: deliveryFeeData } = useDeliveryFee(
		Cart?.cart_item?.[0]?.product?.vendor?.lat ?? User?.lat ?? undefined,
		Cart?.cart_item?.[0]?.product?.vendor?.lng ?? User?.lng ?? undefined,
		User?.lat ?? undefined,
		User?.lng ?? undefined,
		vendor_type,
		quote?.vehicle_class ?? 'motorbike',
		deliveryType
	);

	// <--------------STATES--------------->
	const [ modalPage , setModalPage ]= useState(1)
	const [CheckoutVisible, setCheckoutVisible] = useState(false)
	const [CheckoutRequestID, setCheckoutRequestID] = useState<string | null>(null)

	const normalisePhone = (raw?: string | null) => {
		if (!raw) return null;
		let cleaned = raw.replace(/[^0-9]/g, '');
		if (cleaned.startsWith('254')) cleaned = cleaned.substring(3);
		if (cleaned.startsWith('0')) cleaned = cleaned.substring(1);
		return cleaned;
	};

	/**
	 * The number to bill, in preference order: the payment method the customer
	 * marked default in Settings, then their profile number.
	 *
	 * Settings → Payment Methods wrote to `payment_methods` and nothing ever read
	 * it back, so a customer who saved the M-Pesa line they actually pay with was
	 * still billed on their profile number and had to retype it every checkout.
	 */
	const preferredPayoutPhone = useMemo(() => {
		const methods = User?.payment_methods ?? [];
		const preferred = methods.find((m) => m?.isDefault && m?.phone) ?? methods.find((m) => m?.phone);
		return normalisePhone(preferred?.phone ?? User?.phone_number);
	}, [User?.payment_methods, User?.phone_number]);

	const [PhoneNumber, setPhoneNumber] = useState<string | null>(() => preferredPayoutPhone);

	useEffect(() => {
		// Only fill a blank field — never overwrite a number the customer is typing.
		if (preferredPayoutPhone && !PhoneNumber) {
			setPhoneNumber(preferredPayoutPhone);
		}
	}, [preferredPayoutPhone]);
	const [PaymentLoading, setPaymentLoading] = useState(false)
	const [ConfirmPaymentLoading, setConfirmPaymentLoading] = useState(false)
	const [SuccessModal, setSuccessModal] =useState(false)
	const [ErrorMessage, setErrorMessage] =useState("")
	const [ErrorModal, setErrorModal] =useState(false)
	const [idempotencyKey, setIdempotencyKey] = useState<string>(() => randomUUID())
	const [pendingOrderId, setPendingOrderId] = useState<string | null>(null)
	const [pollAttempts, setPollAttempts] = useState(0)
	const [paymentTimedOut, setPaymentTimedOut] = useState(false)
	const pollingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
	const pollingIntervalRef = useRef<ReturnType<typeof setTimeout> | null>(null)
	// <-------------VARIABLES------------->
	// Delivery-type selector labels only — the authoritative fee is quote.delivery_fee.
	// No `?? 50` fallback. A hardcoded price shown when the endpoint is
	// unreachable is the exact defect the "business values are rows" rule exists
	// to prevent — the customer would be quoted a figure the platform does not
	// charge. `null` renders as "—" and the option still works; the authoritative
	// total always comes from the quote.
	const exchangeFee = deliveryFeeData?.exchange_fee ?? null;
	const refillMineFee = deliveryFeeData?.refill_mine_fee ?? null;
	// Subtracted in cents. `refillMineFee - exchangeFee` on two decimal strings
	// is a float subtraction of two figures the server sent precisely so that it
	// would not be one.
	const refillMinePremium =
		exchangeFee !== null && refillMineFee !== null
			? (compareMoney(refillMineFee, exchangeFee) > 0
				? subtractMoney(refillMineFee, exchangeFee)
				: "0.00")
			: null;
	const depositPerBottle = quote?.bottle_deposit ?? null;

	// Cash availability is the server's answer, not a rule restated here.
	// Absent (an older backend, or the quote still loading) means offer it and
	// let checkout decide — the same refusal, one step later, rather than
	// hiding a payment method because a field has not arrived yet.
	const cashAvailable = quote?.cash?.available !== false;
	const cashReason = quote?.cash?.reason ?? null;
	// `—` for a figure that has not arrived, never a plausible-looking zero.
	const money = (v: string | null) => (v === null ? '—' : formatMoneyShort(v));

	const CartLoaded = !isCartLoading;

	// ── Every line item below is server-computed ──────────────────────────────
	// Decimal strings throughout — rendered with `formatMoney`, tested for
	// presence with `isZeroMoney`, and never summed here: `total` is the
	// server's and this screen has no business re-deriving it.
	const subtotal = quote?.product_subtotal ?? Cart?.total_amount ?? "0";
	const deliveryFee = quote?.delivery_fee ?? "0";
	const serviceFee = quote?.service_fee ?? Cart?.service_fee ?? "0";
	const surgeFee = quote?.surge_fee ?? "0";
	const deliveryMarkup = quote?.delivery_markup ?? "0";
	const payload_surcharge = quote?.payload_surcharge ?? "0";
	const staircase_surcharge = quote?.staircase_surcharge ?? "0";
	const bottle_fee_total = quote?.bottle_deposit ?? "0";
	const debt_settlement = quote?.debt_settlement ?? "0";
	const welcome_discount = quote?.welcome_discount ?? "0";
	const mpesa_discount = quote?.mpesa_discount ?? "0";
	const wallet_discount = quote?.wallet_discount ?? "0";
	// Signed: negative when the rounding takes money off. Rendered whenever it
	// is not zero, because a column that does not add up to the button is the
	// complaint the itemised breakdown exists to answer.
	const rounding_adjustment = quote?.rounding_adjustment ?? "0";
	const finalTotal = quote?.total ?? "0";

	// Platform rules, surfaced before checkout rather than as a 400 afterwards.
	const moqShortfallKg = quote?.moq_kg
		? Math.max(0, quote.moq_kg - (quote.total_weight_kg ?? 0))
		: 0;
	const isOutOfRange = quote ? quote.distance_km > quote.max_distance_km : false;
	// The shop being shut is not the basket being wrong, and it is checked
	// first: telling somebody to add KSH 120 to reach a minimum at a store that
	// closed twenty minutes ago sends them to do work that will not help.
	// Absent means open — an older backend, or a quote still loading, should
	// not close a store this screen cannot see the state of.
	const storeClosedReason = quote?.store && quote.store.accepting === false
		? quote.store.reason
		: null;
	const checkoutBlockedReason = !User?.lat || !User?.lng || (User.lat === 0 && User.lng === 0)
		? "Set your delivery location to see the total."
		: storeClosedReason
			? storeClosedReason
			: quote && !quote.checkout_ready
				? quote.warnings[0]
				: null;
	const canCheckout = !!quote?.checkout_ready && !isQuoteLoading && !checkoutBlockedReason;

	// <-------------FUNCTIONS------------->
	// API CALLS
	const fetch_cart = useCallback(async () => {
		await refetchCart();
	}, [refetchCart]);
// console.log(Cart)
	const Checkout = async () => {
		if (!User?.lat || !User?.lng || (User.lat === 0 && User.lng === 0)) {
			Toast.error("Missing Location", "Please set your delivery location on the map before checking out.");
			return;
		}
		if (!quote) {
			Toast.error("Price unavailable", "We couldn't price your cart. Pull down to refresh and try again.");
			return;
		}
		if (!quote.checkout_ready) {
			setErrorMessage(quote.warnings[0] || "This order doesn't meet the delivery requirements yet.");
			setErrorModal(true);
			return;
		}
		// Server-side format is 2547XXXXXXXX / 2541XXXXXXXX.
		const fullPhone = PhoneNumber ? `254${PhoneNumber}` : null;
		if (!fullPhone || !/^254[17]\d{8}$/.test(fullPhone)) {
			Toast.error("Invalid Phone", "Enter a valid Safaricom number, e.g. 712345678.");
			return;
		}

		setPaymentLoading(true)
		// Only the cart id, destination and phone. The server prices the order —
		// a client-supplied amount would be a price-manipulation vector.
		const payload = {
			phone: fullPhone,
			id: Cart?.id,
			lat: User.lat,
			lng: User.lng,
			delivery_type: deliveryType,
			payment_method: PaymentMethod || "mpesa",
		}
		try {
			const response = await api.post<{
				payment_method: string;
				CheckoutRequestID: string | null;
				order_id: string;
				/** Decimal string — what was actually charged. */
				amount: string;
			}>(ROUTES.CHECKOUT, payload);

			if (response.payment_method === "cash") {
				// Cash orders are complete immediately — nothing to poll for.
				await refetchCart()
				fetchCart()
				setPaymentLoading(false)
				setCheckoutVisible(false)
				// The order id goes with it. Without it the confirmation screen
				// has nothing to track and its "Track Order" button could only
				// fall back to the whole list.
				router.push({
					pathname: "/(screens)/order-confirmation",
					params: { orderId: response.order_id },
				})
				return;
			}

			setCheckoutRequestID(response.CheckoutRequestID)
			setPendingOrderId(response.order_id)
			setPollAttempts(0)
			await refetchCart()
			fetchCart()
			setPaymentLoading(false)
			nextPage()
			setModalPage(3)
		} catch (error: unknown) {
			setPaymentLoading(false)
			const status = error instanceof ApiError ? error.status : 0;
			const message = errorMessage(error, "Could not reach the payment server.");

			if (status === 401) {
				// The client already signed out; just route back to sign-in.
				Toast.error("Session Expired", "Please log in again to continue.");
				router.replace("/(Auth)/sign-in/screen");
				return;
			}
			// 400 (distance/stock/MOQ), 402 (debt), 409 (locked cart or orphaned
			// payment) all carry an actionable backend message — show it as-is.
			if (status === 400 || status === 402 || status === 409) {
				setErrorMessage(message);
				setErrorModal(true);
				setCheckoutVisible(false);
				return;
			}
			Toast.error("Checkout Failed", message);
		}
	}

	/**
	 * Poll Safaricom for the outcome of the STK push.
	 *
	 * `isManualConfirm` distinguishes the customer tapping "I've paid" from the
	 * background poll. Terminal M-Pesa result codes stop the loop immediately —
	 * previously the app kept polling for the full 60 s after the customer had
	 * already cancelled the prompt or entered a wrong PIN.
	 */
	const confirmTransaction = useCallback(async (isManualConfirm = false) => {
		if (!CheckoutRequestID) return;
		setConfirmPaymentLoading(true)

		const stopPolling = () => {
			if (pollingTimeoutRef.current) clearTimeout(pollingTimeoutRef.current);
			if (pollingIntervalRef.current) clearTimeout(pollingIntervalRef.current);
			pollingTimeoutRef.current = null;
			pollingIntervalRef.current = null;
		};

		try {
			const response = await api.post<{ code?: string; message?: string }>(
				ROUTES.CONFIRM_PAYMENT,
				{ CheckoutRequestID }
			);

			if (response?.code === "0") {
				stopPolling();
				setCheckoutVisible(false)
				setIdempotencyKey(randomUUID());
				setConfirmPaymentLoading(false)
				setCheckoutRequestID(null)
				// Read before it is cleared: `setPendingOrderId(null)` below used
				// to run immediately before the push, so the one screen that
				// needs the id was the one place it had already been discarded.
				const confirmedOrderId = pendingOrderId
				setPendingOrderId(null)
				await refetchCart()
				fetchCart()
				router.push({
					pathname: "/(screens)/order-confirmation",
					params: confirmedOrderId ? { orderId: confirmedOrderId } : {},
				})
				return;
			}

			// Terminal failures — no amount of further polling changes these.
			if (response?.code && TERMINAL_MPESA_CODES.has(response.code)) {
				stopPolling();
				setCheckoutVisible(false)
				setErrorMessage(response.message || "The payment was not completed.")
				setErrorModal(true)
				setConfirmPaymentLoading(false)
				return;
			}

			if (isManualConfirm) {
				stopPolling();
				setCheckoutVisible(false)
				setErrorMessage(response?.message || "Payment not confirmed yet. Check your M-Pesa messages and try again.")
				setErrorModal(true)
			}
			setConfirmPaymentLoading(false)
		} catch (error: unknown) {
			if (isManualConfirm) {
				stopPolling();
				Toast.error("Verification Failed", errorMessage(error, "Could not verify your payment."));
			}
			setConfirmPaymentLoading(false)
		}
	}, [CheckoutRequestID, api, fetchCart, refetchCart, router])

	// Auto-poll the payment with a widening interval (3s → 5s → 8s, capped) and a
	// 90s ceiling. A fixed 5s poll was both chattier than necessary early on and
	// gave up while Safaricom was still processing.
	useEffect(() => {
		if (!CheckoutRequestID || modalPage !== 3) return;

		let cancelled = false;
		let attempt = 0;

		const scheduleNext = () => {
			if (cancelled) return;
			const delay = POLL_INTERVALS_MS[Math.min(attempt, POLL_INTERVALS_MS.length - 1)];
			pollingIntervalRef.current = setTimeout(async () => {
				attempt += 1;
				setPollAttempts(attempt);
				await confirmTransaction();
				scheduleNext();
			}, delay);
		};
		scheduleNext();

		pollingTimeoutRef.current = setTimeout(() => {
			cancelled = true;
			if (pollingIntervalRef.current) clearTimeout(pollingIntervalRef.current);
			setConfirmPaymentLoading(false);
			setPaymentTimedOut(true);
		}, POLL_CEILING_MS);

		return () => {
			cancelled = true;
			if (pollingIntervalRef.current) clearTimeout(pollingIntervalRef.current);
			if (pollingTimeoutRef.current) clearTimeout(pollingTimeoutRef.current);
		};
	}, [CheckoutRequestID, modalPage, confirmTransaction]);

	// ANIMATIONS 
	const translateX = useSharedValue(0)

	const animatedTranslateX = useAnimatedStyle(()=>({
		transform: [{translateX: translateX.value}]
	}))

	const nextPage = ()=>{
		if (translateX.value != -width*2){
			translateX.value = withTiming(translateX.value - width, {duration: 500} )
		}
	}

	const prevPage = ()=>{
		if (translateX.value != 0){
			translateX.value = withTiming(translateX.value + width, {duration: 500} )
		}
	}

	const initialPage = ()=>{
		if (translateX.value != 0){
			translateX.value = withTiming(0, {duration: 500} )
		}
	}

	useEffect(()=>{
		fetch_cart()
	},[])

	if (!User && !isCartLoading) {
		return (
			<DataFallbackUI 
				title="User data unavailable"
				message="We couldn't load your profile required for checkout. Please retry or go home."
				onRetry={() => fetch_cart()}
			/>
		);
	}

	return (
		<>
			<StatusBar
				translucent
				backgroundColor={darkTheme?"black":"white"}
				barStyle={darkTheme?"light-content":"dark-content"}
			/>

			<SafeAreaView className={`flex-1 w-full ${darkTheme?"bg-black":""}`}>
				<Animated.View 
					className="flex-1 pb-2"
					style={{
								marginBottom: 50,
							}}
				>
					<View style={{ overflow: "hidden", paddingBottom: 4 }}>
					<View 
						className={`flex-row items-center px-5 py-3 pb-4 mb-2 z-30`}
						style={{ 
							backgroundColor: darkTheme ? "#000" : "#fff",
							borderBottomWidth: 1, 
							borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
							...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
						}}
					>
						<PressableScale
							className="mr-4 z-10"
							onPress={() => router.back()}
							activeOpacity={0.6}
						>
							<BackButtonMinimal/>
						</PressableScale>
						<Text className={`text-xl font-sans-bold tracking-tight ${darkTheme?"text-white":"text-black"}`}>Your Cart</Text>
					</View>
					</View>
					<View className="flex-1 gap-3">
						<ScrollView
							className="flex-1"
							showsVerticalScrollIndicator={false}
							overScrollMode="never"
							snapToAlignment="start"
							contentContainerStyle={{ paddingBottom: 120 }}
							scrollEventThrottle={16}
							refreshControl={
								<RefreshControl
									refreshing={isRefetching}
									onRefresh={refetchCart}
									tintColor={darkTheme ? "white" : "black"}
									colors={[BRAND.primary]}
								/>
							}
							>
							
							{/*
							  * An empty cart is "no items", not "no response".
							  *
							  * This read `Cart === undefined`, which is the one value a
							  * *successful* fetch never produces: `fetch_detailed_cart`
							  * returns `None` when the customer has no cart row at all
							  * (so `data` is `null`), and a cart object with
							  * `cart_item: []` when the row exists but has been emptied.
							  * `null !== undefined`, so both fell through to the items
							  * branch below, which mapped over nothing and drew nothing —
							  * a header over a blank screen, with no way to tell a broken
							  * page from an empty basket.
							  *
							  * The predicate below is the one the other six conditions in
							  * this file already use; only this one, which decides whether
							  * the customer sees anything at all, was different.
							  */}
							{CartLoaded && (Cart?.cart_item?.length ?? 0) === 0 ? (
								<View className="mt-10 flex-1">
									<EmptyState 
										mood="sad" 
										title="Your cart is empty" 
										subtitle="You've not yet added anything to your cart." 
										ctaLabel="Continue Shopping"
										onCtaPress={() => router.push("/(screens)")}
									/>
								</View>
							):(
								<View className="min-h-full  p-4 gap-5 ">
									{/* Cart Header */}

									{/* Cart Items */}
									<View className="gap-4">
										{!CartLoaded ? (
											[...Array(3)].map((_, index) => (
												<CartItemSkeleton key={index} />
											))
											): (
												Cart?.cart_item?.map((item: any) => {
													return(
													<CartItem data={item} key={item.id} func={fetch_cart}  />
													)
												})
											)}
									</View>

									{/* Delivery Type Selection */}
									{CartLoaded && (Cart?.cart_item?.length ?? 0) > 0 && vendor_type !== 'wholesale_b2b' && (
										<View className={`w-full gap-3 p-5 rounded-[24px] mt-2 mb-2 ${darkTheme ? "bg-[#1B1F24]" : "bg-white border border-gray-100"}`}>
											<Text className={`text-lg font-sans-bold ${darkTheme ? 'text-white' : 'text-black'}`}>Which bottle?</Text>
											
											{([
												{
													value: 'exchange' as BottleOption,
													title: 'Exchange my empty bottle',
													detail: `Hand your empty to the rider and get a filled one. ${money(exchangeFee)} delivery.`,
												},
												{
													value: 'refill_mine' as BottleOption,
													title: 'Refill my own bottle',
													// The reason this option exists. Stated plainly, because
													// "quick swap" told a customer nothing about whose bottle
													// arrives at their door.
													detail: `We collect your bottle, refill it and bring the same one back — nobody else drinks from it.${refillMinePremium ? ` +${money(refillMinePremium)} for the round trip.` : ''}`,
												},
												{
													value: 'new_bottle' as BottleOption,
													title: 'I need a bottle',
													// Refundable, said in the option itself rather than in a
													// footnote under it. Calling a deposit a fee tells the
													// customer the money is gone.
													detail: `You keep the bottle. ${money(depositPerBottle)} deposit — refundable when you return it.`,
												},
											]).map((option) => (
												<PressableScale
													key={option.value}
													activeOpacity={0.7}
													onPress={() => setDeliveryType(option.value)}
													className={`w-full p-4 rounded-xl border-2 mb-2 ${deliveryType === option.value ? 'border-primary bg-primary/10' : (darkTheme ? 'border-gray-800 bg-[#0e0e0e]' : 'border-gray-200 bg-white')}`}
												>
													<View className="flex-row justify-between items-center">
														<View className="flex-col max-w-[80%]">
															<Text className={`text-base font-sans-bold ${darkTheme ? 'text-white' : 'text-black'}`}>{option.title}</Text>
															<Text className={`text-xs mt-1 ${darkTheme ? 'text-gray-400' : 'text-gray-500'}`}>{option.detail}</Text>
														</View>
														<View className={`w-6 h-6 rounded-full border-2 items-center justify-center ${deliveryType === option.value ? 'border-primary' : 'border-gray-400'}`}>
															{deliveryType === option.value && <View className="w-3 h-3 rounded-full bg-primary" />}
														</View>
													</View>
												</PressableScale>
											))}
										</View>
									)}

									{/* Total */}
									{
										CartLoaded && (Cart?.cart_item?.length ?? 0) > 0 && (
											<View className={`w-full gap-3 p-5 rounded-[24px] mt-2 mb-4 ${darkTheme ? "bg-[#1B1F24]" : "bg-white border border-gray-100"}`}>
												<View className="flex-row justify-between items-center">
													<Text className={`text-base font-sans-medium ${darkTheme ? 'text-gray-400' : 'text-gray-500'}`}>
														Subtotal
													</Text>
													{/* The quote's own subtotal, not the cart's stored
													    `total_amount`. That column is written when the basket
													    changes; `product_subtotal` is summed from the same items
													    the total below was built from. Rendering the stored one
													    puts a figure on this line that the Total does not agree
													    with, which is the whole defect this screen was rewritten
													    to remove. */}
													<Text className={`text-lg font-sans-semibold ${darkTheme ? 'text-white' : 'text-black'}`}>
														{formatMoney(subtotal)}
													</Text>
												</View>
												{!isZeroMoney(bottle_fee_total) && (
													<View className="flex-row justify-between items-center pt-2">
														<View className="flex-col">
															<Text className={`text-base font-sans-medium ${darkTheme ? 'text-gray-400' : 'text-gray-500'}`}>
																Bottle Deposit
															</Text>
															{/* A deposit, not a fee: `customer_bottle_service` holds it
															    as a liability the platform returns when the bottles come
															    back. It is also charged whenever you keep bottles, not
															    only on a first order — "New Bottle Fee / Required for
															    first order" was wrong on both counts and told the
															    customer the money was gone. */}
															<Text className={`text-xs italic ${darkTheme ? 'text-gray-500' : 'text-gray-400'}`}>
																Refundable when you return the bottles
															</Text>
														</View>
														<Text className={`text-lg font-sans-semibold ${darkTheme ? 'text-white' : 'text-black'}`}>
															{formatMoney(bottle_fee_total)}
														</Text>
													</View>
												)}
												{/* An unpaid balance from an earlier order, collected on this
												    one. `create_order` clears it. It was in the quote and in the
												    total and on no line, so the customer paid an unexplained
												    difference — the one charge on this screen that is not for
												    anything in the basket. */}
												{!isZeroMoney(debt_settlement) && (
													<View className="flex-row justify-between items-center pt-2">
														<View className="flex-col flex-1 pr-3">
															<Text className={`text-base font-sans-medium ${darkTheme ? 'text-amber-400' : 'text-amber-700'}`}>
																Previous Balance
															</Text>
															<Text className={`text-xs italic ${darkTheme ? 'text-amber-400/80' : 'text-amber-700/80'}`}>
																Owed from an earlier order — settled by this one
															</Text>
														</View>
														<Text className={`text-lg font-sans-semibold ${darkTheme ? 'text-amber-400' : 'text-amber-700'}`}>
															{formatMoney(debt_settlement)}
														</Text>
													</View>
												)}
												{!isZeroMoney(welcome_discount) && (
													<View className="flex-row justify-between items-center pt-2">
														<View className="flex-col">
															<Text className={`text-base font-sans-medium ${darkTheme ? 'text-green-400' : 'text-green-600'}`}>
																Welcome Offer
															</Text>
															{/* No percentage in this string. `welcome_discount_rate`
															    is a settings row an administrator edits from the
															    console, and it applies to **one** bottle's deposit,
															    not the whole one — so "30% off deposit" was wrong
															    about the rate the moment anybody moved it, and wrong
															    about the base on any order of more than one bottle.
															    The amount beside it is already the truth. */}
															<Text className={`text-xs italic ${darkTheme ? 'text-green-400/80' : 'text-green-600/80'}`}>
																Off your first bottle's deposit
															</Text>
														</View>
														<Text className={`text-lg font-sans-semibold ${darkTheme ? 'text-green-400' : 'text-green-600'}`}>
															- {formatMoney(welcome_discount)}
														</Text>
													</View>
												)}
												<View className="flex-col pb-4 border-b ${darkTheme ? 'border-white/10' : 'border-gray-200'}">
													<View className={`flex-row justify-between items-center`}>
														<Text className={`text-base font-sans-medium ${darkTheme ? 'text-gray-400' : 'text-gray-500'}`}>
															Delivery Fee
														</Text>
														<Text className={`text-lg font-sans-semibold ${darkTheme ? 'text-white' : 'text-black'}`}>
															{formatMoney(deliveryFee)}
														</Text>
													</View>
													{/* A caption, not a line. `delivery_markup` is platform
													    margin *inside* `delivery_fee` — the server says so at
													    the field itself and leaves it out of the `gross` sum —
													    so giving it its own row in the amount column made the
													    column stop adding up: the lines summed to KSH 152.12
													    against a total of KSH 144.40, adrift by exactly the
													    markup. Shown here it stays visible without being
													    counted twice. */}
													{!isZeroMoney(deliveryMarkup) && (
														<Text className={`text-xs italic mt-1 ${darkTheme ? 'text-gray-500' : 'text-gray-400'}`}>
															Includes {formatMoney(deliveryMarkup)} logistics handling.
														</Text>
													)}
													{vendor_type === 'wholesale_b2b' && (
														<Text className={`text-xs italic mt-1 ${darkTheme ? 'text-gray-500' : 'text-gray-400'}`}>
															* 0% commission on delivery. Fees are set directly by the wholesale vendor.
														</Text>
													)}
												</View>
												<View className={`flex-row justify-between items-center pb-4 border-b ${darkTheme ? 'border-white/10' : 'border-gray-200'}`}>
													<Text className={`text-base font-sans-medium ${darkTheme ? 'text-gray-400' : 'text-gray-500'}`}>
														Service Fee
													</Text>
													<Text className={`text-lg font-sans-semibold ${darkTheme ? 'text-white' : 'text-black'}`}>
														{formatMoney(serviceFee)}
													</Text>
												</View>

												{/* Peak-hour surcharge. Previously charged silently. */}
												{!isZeroMoney(surgeFee) && (
													<View className="flex-row justify-between items-center pt-2">
														<View className="flex-row items-center gap-1">
															<Ionicons name="trending-up" size={16} color={BRAND.primary} />
															<Text className={`text-base font-sans-medium ${darkTheme ? 'text-gray-400' : 'text-gray-500'}`}>
																Peak Hour Surcharge
															</Text>
														</View>
														<Text className={`text-lg font-sans-semibold ${darkTheme ? 'text-white' : 'text-black'}`}>
															{formatMoney(surgeFee)}
														</Text>
													</View>
												)}

												
												{/* --- Surcharges --- */}
												{!isZeroMoney(payload_surcharge) && (
													<View className="flex-row justify-between items-center pt-2">
														<View className="flex-row items-center gap-1">
															<Text className={`text-base font-sans-medium ${darkTheme ? 'text-gray-400' : 'text-gray-500'}`}>
																Heavy Payload Surcharge
															</Text>
															{/* Info Icon placeholder - could be added later */}
														</View>
														<Text className={`text-lg font-sans-semibold ${darkTheme ? 'text-white' : 'text-black'}`}>
															{formatMoney(payload_surcharge)}
														</Text>
													</View>
												)}
												{!isZeroMoney(staircase_surcharge) && (
													<View className="flex-row justify-between items-center pt-2">
														<View className="flex-row items-center gap-1">
															<Text className={`text-base font-sans-medium ${darkTheme ? 'text-gray-400' : 'text-gray-500'}`}>
																Staircase Surcharge (Floor {User?.floor_level ?? 0})
															</Text>
															{/* Info Icon placeholder */}
														</View>
														<Text className={`text-lg font-sans-semibold ${darkTheme ? 'text-white' : 'text-black'}`}>
															{formatMoney(staircase_surcharge)}
														</Text>
													</View>
												)}
												{/* Paying by M-Pesa instead of cash is worth
												    `mpesa_payment_discount` off the total. It was
												    applied by the server and rendered nowhere, so the
												    total sat below the sum of the lines with nothing
												    accounting for the difference — the same defect as
												    `debt_settlement`, and self-defeating here: the
												    whole reason this is framed as a discount rather
												    than a cash surcharge is so the customer sees they
												    are being rewarded. A reward nobody is shown steers
												    nobody. */}
												{!isZeroMoney(mpesa_discount) && (
													<View className="flex-row justify-between items-center pt-2">
														<View className="flex-col flex-1 pr-3">
															<Text className="text-base font-sans-medium" style={{ color: BRAND.primary }}>
																M-Pesa Payment Discount
															</Text>
															<Text className={`text-xs italic ${darkTheme ? 'text-gray-500' : 'text-gray-400'}`}>
																For paying by M-Pesa instead of cash
															</Text>
														</View>
														<Text className="text-lg font-sans-semibold" style={{ color: BRAND.primary }}>
															- {formatMoney(mpesa_discount)}
														</Text>
													</View>
												)}
												{!isZeroMoney(wallet_discount) && (
													<View 
														className="flex-row justify-between items-center pt-2 pb-2 border-b border-dashed"
														style={{ borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200 }}
													>
														<View className="flex-col">
															<Text className="text-base font-sans-medium" style={{ color: BRAND.primary }}>
																Drop Cashback Applied
															</Text>
														</View>
														<Text className="text-lg font-sans-semibold" style={{ color: BRAND.primary }}>
															- {formatMoney(wallet_discount)}
														</Text>
													</View>
												)}

												{!isZeroMoney(rounding_adjustment) && (
													<View className="flex-row justify-between items-center pt-2">
														<View className="flex-col flex-1 pr-3">
															<Text className={`text-base font-sans-medium ${darkTheme ? 'text-gray-300' : 'text-gray-700'}`}>
																Rounding
															</Text>
															<Text className={`text-xs italic ${darkTheme ? 'text-gray-500' : 'text-gray-400'}`}>
																M-Pesa charges whole shillings only
															</Text>
														</View>
														<Text className={`text-lg font-sans-semibold ${darkTheme ? 'text-gray-300' : 'text-gray-700'}`}>
															{isNegativeMoney(rounding_adjustment)
																? `- ${formatMoney(subtractMoney("0", rounding_adjustment))}`
																: `+ ${formatMoney(rounding_adjustment)}`}
														</Text>
													</View>
												)}

												<View className="flex-row justify-between items-center pt-4">
													<Text className={`text-xl font-sans-bold tracking-tight ${darkTheme ? 'text-white' : 'text-black'}`}>
														Total Amount
													</Text>
													<Text className={`text-2xl font-sans-bold tracking-tight ${darkTheme ? 'text-accentbg' : 'text-primary'}`}>
														{formatMoney(finalTotal)}
													</Text>
												</View>
											</View>
										)
									}

									{/* Platform rules, surfaced before checkout rather than as an error after it */}
									{CartLoaded && (Cart?.cart_item?.length ?? 0) > 0 && moqShortfallKg > 0 && (
										<View className={`w-full mt-2 p-4 rounded-2xl border ${darkTheme ? 'bg-amber-500/10 border-amber-500/30' : 'bg-amber-50 border-amber-200'}`}>
											<View className="flex-row items-center gap-2">
												<Ionicons name="scale-outline" size={18} color="#d97706" />
												<Text className={`flex-1 text-sm font-sans-medium ${darkTheme ? 'text-amber-300' : 'text-amber-800'}`}>
													Add {moqShortfallKg.toFixed(0)} kg more to meet the {quote?.moq_kg?.toFixed(0)} kg wholesale minimum
													({(quote?.total_weight_kg ?? 0).toFixed(0)} / {quote?.moq_kg?.toFixed(0)} kg).
												</Text>
											</View>
										</View>
									)}
									{/*
									  * One explanation of a refusal, and it is the server's.
									  *
									  * There used to be two. This banner re-derived "is it too
									  * far?" locally and printed its own sentence, while the
									  * server's own reason — already computed by the same
									  * `validate_quote` that will refuse the order — was shown
									  * again as `checkoutBlockedReason`. The customer was told
									  * the same thing twice, in different words.
									  *
									  * And the local copy had the number wrong. It rendered the
									  * limit with `.toFixed(0)`, and `(2.5).toFixed(0)` is "3":
									  * a cart that explained a refusal by quoting a 3 km rule
									  * this platform does not have. The radius is deliberately a
									  * *decimal* setting — the guide is explicit that storing it
									  * as an int would silently make 2.5 into 2 — and rounding it
									  * for display reintroduces exactly that, on the sentence
									  * telling somebody why they cannot buy water.
									  */}
									{CartLoaded && (Cart?.cart_item?.length ?? 0) > 0 && checkoutBlockedReason && (
										<View className={`w-full mt-2 p-4 rounded-2xl border ${darkTheme ? 'bg-red-500/10 border-red-500/30' : 'bg-red-50 border-red-200'}`}>
											<View className="flex-row items-center gap-2">
												<Ionicons name={isOutOfRange ? "location-outline" : "alert-circle-outline"} size={18} color="#ef4444" />
												<Text className={`flex-1 text-sm font-sans-medium ${darkTheme ? 'text-red-300' : 'text-red-700'}`}>
													{checkoutBlockedReason}
												</Text>
											</View>
										</View>
									)}
									{CartLoaded && (Cart?.cart_item?.length ?? 0) > 0 && quoteError && (
										<PressableScale className="w-full mt-2" onPress={() => refetchQuote()}>
											<View className={`w-full p-4 rounded-2xl border ${darkTheme ? 'bg-gray-800 border-gray-700' : 'bg-gray-50 border-gray-200'}`}>
												<Text className={`text-sm font-sans-medium text-center ${darkTheme ? 'text-gray-300' : 'text-gray-700'}`}>
													{errorMessage(quoteError, "Couldn't calculate your total.")} Tap to retry.
												</Text>
											</View>
										</PressableScale>
									)}

									{/* Place Order Button */}
									{CartLoaded && (Cart?.cart_item?.length ?? 0) > 0 && (
										<PressableScale
											className="w-full mt-2"
											activeOpacity={0.7}
											disabled={!canCheckout}
											onPress={() => {
												if (!canCheckout) {
													Toast.info("Not ready yet", checkoutBlockedReason || "Please resolve the items above first.");
													return;
												}
												setCheckoutVisible(true);
											}}
										>
											<View
												className={`w-full py-4 rounded-full flex-row items-center justify-center ${canCheckout ? 'bg-primary' : (darkTheme ? 'bg-gray-700' : 'bg-gray-300')}`}
											>
												{isQuoteLoading ? (
													<ActivityIndicator color="white" />
												) : (
													<Text className={`text-xl font-sans-bold tracking-tight ${canCheckout ? 'text-white' : (darkTheme ? 'text-gray-400' : 'text-gray-500')}`}>
														{canCheckout ? `Checkout • ${formatMoney(finalTotal)}` : "Checkout unavailable"}
													</Text>
												)}
											</View>
										</PressableScale>
									)}
								</View>
							)}
						</ScrollView>
					</View>

				</Animated.View>
			</SafeAreaView>
			{/* Modals */}
			{/* <------------------------------CHECKOUT MODAL------------------------------> */}
			<Modal 
				visible={CheckoutVisible} 
				transparent={true}
				animationType="slide"
				onRequestClose={() => {
					setCheckoutVisible(false)
					setModalPage(1)
					initialPage()
				}}
			>
				<PressableScale 
					className={`flex-1 w-full justify-end bg-black/40`}
					activeOpacity={1}
					onPress={() => {
						setCheckoutVisible(false)
						setModalPage(1)
						initialPage()
					}}
				>
					<PressableScale 
						activeOpacity={1} 
						className={`min-w-full ${darkTheme?"bg-black":"bg-white"} rounded-t-2xl pb-4 border-t ${darkTheme ? 'border-white/10' : 'border-gray-200'}`}
						onPress={(e) => e.stopPropagation()}
					>
						<View className={`w-full items-center h-[60px] justify-center`}>
							<Text className={`text-2xl font-heading-semibold ${darkTheme?"text-white":"text-black"}`}>Checkout</Text>
						</View>
						<View className=" py-7 items-center flex-row justify-evenly w-[90%] self-center">
							<Animated.View className={`w-full flex-row absolute self-center rounded-full gap-2 h-1  m-2`}>
								{/* progress bar */}
								<Animated.View className={`rounded-full flex-1 h-full bg-primary `}
									style={{
									}}
								/>
								<Animated.View className={`rounded-full flex-1 h-full ${modalPage >= 2 ? "bg-primary": darkTheme?"bg-gray-200/20":"bg-white"} `}
									style={{
									}}
								/>
								<Animated.View className={`rounded-full flex-1 h-full ${modalPage >= 3 ? "bg-primary": darkTheme?"bg-gray-200/20":"bg-white"} `}
									style={{
									}}
								/>
							</Animated.View>
						</View>
						{/* pager View  PAGES [ REVIEW ITEMS, DELIVERY ADDRESS, PAYMENT METHOD, PAYMENT]*/}
							<ScrollView>
								<View className={`w-full pb-[50px] flex-row overflow-scroll flex-nowrap`}>
											<Animated.View className="flex-row max-h-[300px]"
												style={[
													animatedTranslateX
												]}
											>
												<View
													className="gap-3"
													style={{
														minWidth: width,
													}}
												>
													<Text className={`font-sans-semibold text-xl self-center ${darkTheme?"text-white":""}`}>
														Payment method
													</Text>
													<View className={`px-4 py-2 items-center`}>
														<Text className={`text-base ${darkTheme?"text-white":""}`}>
															Choose your preferred payment method
														</Text>
													</View>
													<View className="flex-row justify-center gap-4 px-4 mt-2">
														{/* M-PESA */}
														<PressableScale
															activeOpacity={0.6}
															className="flex-1 h-[60px] justify-center items-center max-w-[160px]"
															onPress={()=> {
																setPaymentMethod("mpesa")
																nextPage()
																setModalPage(2)
															}}
														>
															<View className={`w-full h-full justify-center items-center rounded-2xl bg-green-700`}>
																<Image source={images.mpesa_logo} className="h-[40px] w-[90px]" resizeMode="contain" />
															</View>
														</PressableScale>

														{/* Cash on Delivery.
														    Offered only when the server says so. The rules —
														    a first completed order, a value ceiling, a
														    distance limit — are settings rows, so the app
														    neither restates them nor guesses: it renders the
														    server's own sentence. Letting somebody pick cash
														    and be refused after entering a phone number is
														    the same refusal with a wasted trip attached. */}
														<PressableScale
															activeOpacity={cashAvailable ? 0.6 : 1}
															disabled={!cashAvailable}
															accessibilityState={{ disabled: !cashAvailable }}
															className="flex-1 h-[60px] justify-center items-center max-w-[160px]"
															onPress={() => {
																if (!cashAvailable) {
																	Toast.info("Cash not available", cashReason ?? "")
																	return
																}
																setPaymentMethod("cash")
																nextPage()
																setModalPage(2)
															}}
														>
															<View
																className={`w-full h-full justify-center items-center rounded-2xl border ${darkTheme ? "bg-slate-800 border-slate-700" : "bg-white border-slate-200"}`}
																style={cashAvailable ? undefined : { opacity: 0.45 }}
															>
																<Ionicons name="cash-outline" size={24} color={BRAND.primary} />
																<Text className={`font-sans-bold mt-1 text-xs ${darkTheme ? "text-slate-300" : "text-slate-700"}`}>Cash on Delivery</Text>
															</View>
														</PressableScale>
													</View>
													</View>

												<View
													className=" py-3"
													style={{
														minWidth: width,
													}}
												>
													{
														PaymentMethod == "mpesa" && (
															<View className={`w-full  items-center gap-4`}>
																<Image source={images.mpesa_logo} className="h-[40px] w-[100px]" resizeMode="contain"/>
																<Text className={`text-base font-sans-semibold ${darkTheme?"text-white":""}`}>
																	Enter your Phone Number:
																</Text>

																<View className={`px-5 flex-row h-[50px] min-w-[250px] gap-2 items-center rounded-full ${darkTheme?"bg-gray-200/20":"bg-white"}`}>
																	<Ionicons name="call" size={20} color={BRAND.primary} />
																	<Text className={`text-base font-sans-semibold ${darkTheme?"text-white":""}`}>+254</Text>
																	<TextInput
																		placeholder="712345678"
																		placeholderTextColor={darkTheme ? "#888" : "#A0AEC0"}
																		keyboardType='numeric'
																		maxLength={10}
																		className={`flex-1 h-full text-base ${darkTheme ? "text-white" : "text-black"}`}
																		onChangeText={(text) => {
																			// Strip non-digits, leading 0 or country code
																			let cleaned = text.replace(/[^0-9]/g, '');
																			if (cleaned.startsWith('0')) cleaned = cleaned.substring(1);
																			if (cleaned.startsWith('254')) cleaned = cleaned.substring(3);
																			setPhoneNumber(cleaned);
																		}}
																	/>
																</View>
																<View 
																	className="px-5 items-center mb-2"
																	style={{
																		maxWidth: width,
																		width
																	}}
																>
																	<Text className={`text-sm text-center ${darkTheme?"text-gray-300":"text-gray-600"}`}>
																		When you press continue, an M-PESA prompt will be sent to your phone to complete the transaction.
																	</Text>
																</View>
																<View className={` flex-row justify-center gap-3`}>
																	<PressableScale
																		disabled={!PhoneNumber || PhoneNumber.length < 8 || PaymentLoading}
																		activeOpacity={0.6}
																		onPress={()=>{
																			prevPage()
																			setModalPage(1)
																		}}
																	>
																		<BackButtonMinimal />
																	</PressableScale>
																	<PressableScale
																		disabled={!PhoneNumber || PhoneNumber.length < 8 || PaymentLoading}
																		activeOpacity={0.6}
																		onPress={()=>{
																			Checkout()
																			
																		}}
																	>
																		<View className={`h-[40px] min-w-[200px] items-center justify-center px-6 rounded-full bg-green-500`}>
																			{PaymentLoading ? (
																				<View className={`w-9 h-9 items-center justify-center`}>
																					<ActivityIndicator size="small" color={darkTheme ? BRAND.bgDark : BRAND.white} />
																				</View>
																			) : (
																				<Text className={`font-sans-bold text-xl ${darkTheme?"":"text-white"}`}>Continue</Text>
																			)}
																		</View>
																	</PressableScale>
																</View>
															</View>
														)
													}
													{
														PaymentMethod == "cash" && (
															<View className={`w-full items-center gap-4 px-6`}>
																<View className={`w-16 h-16 rounded-full items-center justify-center mb-2 ${darkTheme ? "bg-slate-800" : "bg-green-50"}`}>
																	<Ionicons name="cash" size={32} color={BRAND.primary} />
																</View>
																<Text className={`text-xl font-sans-bold text-center ${darkTheme ? "text-white" : "text-slate-900"}`}>
																	Pay with Cash
																</Text>
																<Text className={`text-center text-base mb-4 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
																	You will pay <Text className="font-sans-bold">{formatMoney(finalTotal)}</Text> in cash to the rider upon delivery.
																</Text>
																
																<View className={` flex-row justify-center gap-3 w-full`}>
																	<PressableScale
																		disabled={PaymentLoading}
																		activeOpacity={0.6}
																		onPress={()=>{
																			prevPage()
																			setModalPage(1)
																		}}
																	>
																		<BackButtonMinimal />
																	</PressableScale>
																	<PressableScale
																		disabled={PaymentLoading}
																		activeOpacity={0.6}
																		onPress={()=>{
																			Checkout()
																		}}
																		className="flex-1"
																	>
																		<View className={`h-[50px] w-full items-center justify-center rounded-full bg-green-500`}>
																			{PaymentLoading ? (
																				<ActivityIndicator size="small" color={BRAND.white} />
																			) : (
																				<Text className={`font-sans-bold text-lg text-white`}>Place Order</Text>
																			)}
																		</View>
																	</PressableScale>
																</View>
															</View>
														)
													}
												</View>
												<View
													className=""
													style={{
														minWidth: width,
													}}
												>
													<View className={`w-full items-center gap-5 py-3`}>
														<Text className={`text-xl font-sans-semibold ${darkTheme?"text-white":""}`}>Confirmation</Text>
														{paymentTimedOut ? (
															// The customer is never stranded: after the polling window closes
															// the order still exists and can be checked again or opened in
															// Orders. Previously this was a dead end with only a toast.
															<>
																<Text className={`text-base text-center px-4 ${darkTheme?"text-gray-300":"text-gray-600"}`}>
																	We haven&apos;t received confirmation from M-PESA yet. Your order is saved — check your
																	M-PESA messages, then try again.
																</Text>
																<PressableScale
																	activeOpacity={0.6}
																	onPress={() => {
																		setPaymentTimedOut(false);
																		setPollAttempts(0);
																		confirmTransaction(true);
																	}}
																>
																	<View className={`h-[40px] min-w-[200px] items-center justify-center px-6 rounded-full bg-green-500`}>
																		<Text className="font-sans-bold text-lg text-white">Check again</Text>
																	</View>
																</PressableScale>
																<PressableScale
																	activeOpacity={0.6}
																	onPress={() => {
																		setCheckoutVisible(false);
																		setPaymentTimedOut(false);
																		router.push(pendingOrderId
																			? `/(screens)/OrderDetail?orderId=${pendingOrderId}`
																			: "/(screens)/Orders");
																	}}
																>
																	<Text className={`text-base font-sans-medium underline ${darkTheme?"text-gray-300":"text-gray-600"}`}>
																		View my order
																	</Text>
																</PressableScale>
															</>
														) : (
															<Text className={`text-base text-center px-4 ${darkTheme?"text-gray-300":"text-gray-600"}`}>
																{pollAttempts > 0
																	? "Waiting for M-PESA to confirm your payment…"
																	: "Enter your M-PESA PIN on your phone. We'll confirm automatically."}
															</Text>
														)}
														<PressableScale
															disabled={CheckoutRequestID === null || PaymentLoading || ConfirmPaymentLoading || paymentTimedOut}
															activeOpacity={0.6}
															onPress={()=>{
																confirmTransaction(true)
															}}
														>
															<View className={`h-[40px] min-w-[200px] items-center justify-center px-6 rounded-full bg-green-500`}>
																{PaymentLoading || ConfirmPaymentLoading ? (
																	<View className={`w-9 h-9 items-center justify-center`}>
																		<ActivityIndicator size="small" color={darkTheme ? BRAND.bgDark : BRAND.white} />
																	</View>
																) : (
																	<Text className={`font-sans-bold text-xl ${darkTheme?"":"text-white"}`}>Confirm</Text>
																)}
															</View>
														</PressableScale>
													</View>
												</View>
											</Animated.View>
								</View>
								<View className="w-full flex-row items-center justify-center">
									{/* buttons */}
									{/* <PressableScale
										activeOpacity={0.6}
										onPress={()=> {
											nextPage()
										}}
									>
										<View className={`rounded-full px-6 py-2 bg-blue-500`}>
											<Text className={`font-sans-bold text-xl ${darkTheme?"text-black":"text-white"}`}>Next</Text>
										</View>
									</PressableScale> */}
								</View>
							</ScrollView>
					</PressableScale>
				</PressableScale>
			</Modal>

			{/* <------------------------------SUCCESS MODAL------------------------------> */}
			<Modal visible={SuccessModal} transparent animationType="fade">
				<View className="w-full flex-1 items-center justify-center bg-black/50">
					<View className={`min-w-[200px] min-h-[250px] ${darkTheme?"bg-black":"bg-white"} p-7 rounded-xl items-center gap-5`}>
						<View className="h-[160px] w-[160px] items-center justify-center bg-green-500 rounded-full shadow-xl ">
							<Ionicons name="checkmark-circle" size={24} color={BRAND.white} />
						</View>
						<Text className={`text-xl font-sans-semibold ${darkTheme?"text-white":""}`}>Transaction was completed successfully.</Text>
						<View className={`gap-4 flex-row `}>
							<PressableScale
								activeOpacity={0.6}
								onPress={()=>{
									router.push("/(screens)")
								}}
							>
								<Button style={`rounded-full ${darkTheme?"bg-gray-200/20":"bg-white"}`} label={"Continue Shopping "} textStyle={`font-sans-semibold text-lg ${darkTheme?"text-white":"text-black"}`}/>
							</PressableScale>
							<PressableScale
								activeOpacity={0.6}
								onPress={()=>{
									router.push("/(screens)/Orders")
								}}
							>
								<Button style={"bg-primary rounded-full"} label={"See Order "} textStyle={`font-sans-semibold text-lg text-white`}/>
							</PressableScale>
							
						</View>
					</View>
				</View>
			</Modal>

			{/* <------------------------------SUCCESS MODAL------------------------------> */}
			<Modal visible={ErrorModal} transparent animationType="fade">
			<View className="w-full flex-1 items-center justify-center">
					<View className={`min-w-[200px] min-h-[250px] ${darkTheme?"bg-black":"bg-white"} p-7 rounded-xl items-center gap-5`}>
						<View className="h-[100px] w-[100px] items-center justify-center bg-red-500 rounded-full shadow-xl ">
							<Ionicons name="close" size={24} color={BRAND.white} />
						</View>
						<Text className={`text-xl font-sans-semibold ${darkTheme?"text-white":""}`}>{ErrorMessage}</Text>
						<Text className={`text-xl font-sans-semibold ${darkTheme?"text-white":""}`}></Text>
						<View className={`gap-4 flex-row `}>
							<PressableScale
								activeOpacity={0.6}
								onPress={()=>{
									// router.push("/(screens)")
									setErrorModal(false)
								}}
							>
								<Button style={`rounded-full px-5 ${darkTheme?"bg-gray-200/20":"bg-white"}`} label={"Cancel"} textStyle={`font-sans-semibold text-lg ${darkTheme?"text-white":"text-black"}`}/>
							</PressableScale>
							<PressableScale
								activeOpacity={0.6}
								onPress={()=>{
									setErrorModal(false);
									setCheckoutVisible(true);
									setModalPage(3);
								}}
							>
								<Button style={"bg-primary rounded-full px-5"} label={"Re-try"} textStyle={`font-sans-semibold text-lg text-white`}/>
							</PressableScale>
							
						</View>
					</View>
				</View>		
			</Modal>
		</>
	);
}

