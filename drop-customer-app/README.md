# Drop Customer App 💧

> The consumer-facing application for the Drop Multivendor Water Delivery Platform. Built with Expo, React Native, and Tailwind CSS (NativeWind).

## 📱 Overview

The Drop Customer App allows users to browse nearby water vendors, order water (both retail refills and wholesale), track deliveries in real-time, and manage empty bottle returns.

### Core Features
- **Location-based Discovery**: Find nearby vendors using device GPS and GeoSpatial queries (H3 hex indexing).
- **Checkout & Payments**: Seamless integration with Safaricom M-Pesa (STK Push) for instant payments.
- **Real-Time Tracking**: WebSocket integration for live rider location tracking on a map.
- **Gamification & Loyalty**: Welcome discounts, wallet cashback, and repeat-order incentives.
- **Empty Bottle Management**: Track bottle debt and return empty bottles to vendors during delivery (Quick Swap).
- **Dark Mode Support**: Full theming support aligned with the Drop BRAND design system.

## 🛠️ Tech Stack

- **Framework**: React Native with [Expo SDK 54](https://expo.dev/)
- **Routing**: [Expo Router](https://docs.expo.dev/router/introduction/) (File-based routing)
- **Styling**: [NativeWind v4](https://www.nativewind.dev/) (Tailwind CSS)
- **State Management**: [Zustand](https://zustand-demo.pmnd.rs/) (Client state) & [TanStack Query v5](https://tanstack.com/query/latest) (Server state)
- **Authentication**: [Clerk](https://clerk.com/) (Email, Phone OTP, OAuth)
- **Maps**: `react-native-maps` + Google Maps SDK
- **Real-time**: `socket.io-client` for WebSockets
- **Animations**: `react-native-reanimated`

## 🚀 Getting Started

### Prerequisites
- Node.js (v20+)
- pnpm
- Expo CLI (`npm i -g expo-cli`)
- iOS Simulator or Android Emulator

### Installation

1. Install dependencies:
   ```bash
   pnpm install
   ```

2. Configure Environment Variables:
   Create a `.env` file in the root of this app and add:
   ```env
   EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
   EXPO_PUBLIC_BACKEND_BASE_URL=http://<YOUR_IP>:8000

   # Native Maps SDK keys — build-time only, injected by app.config.js.
   # Deliberately not EXPO_PUBLIC_*: they belong in AndroidManifest.xml /
   # Info.plist, not in the JS bundle. One key per platform, because a Google
   # API key can carry only one application restriction.
   GOOGLE_MAPS_ANDROID_API_KEY=...   # restricted to com.drop.customer + SHA-1
   GOOGLE_MAPS_IOS_API_KEY=...       # restricted to bundle id com.drop.customer
   ```
   > **Note**: For physical device testing, `EXPO_PUBLIC_BACKEND_BASE_URL` must be your computer's local IP address, not `localhost`.

   > **Never commit a Google key.** `app.json` carries no key; `app.config.js`
   > reads the two above from the environment (EAS secrets in CI). See
   > [docs/security/google-api-key-rotation.md](../docs/security/google-api-key-rotation.md).

3. Run the app:
   ```bash
   pnpm start
   ```
   Press `a` for Android, `i` for iOS.

## 📂 Project Structure

```
drop-customer-app/
├── app/
│   ├── (Auth)/           # Authentication screens (Login, OTP)
│   ├── (screens)/        # Main app screens (Dashboard, Map, Profile, etc.)
│   └── _layout.tsx       # Root layout & providers
├── API/
│   └── routes/           # Strictly typed API route definitions
├── components/
│   ├── common/           # Reusable UI components (Bento grids, lists)
│   ├── dashboard/        # Dashboard specific components
│   └── ui/               # Base UI elements (Buttons, Inputs, Skeletons)
├── constants/            # Theme colors (BRAND), images, icons
├── context/              # Context providers (ThemeContext)
├── hooks/
│   ├── queries/          # TanStack Query hooks for API fetching
│   └── useWebSocket.ts   # Real-time WebSocket connection logic
├── stores/               # Zustand state stores
└── lib/                  # Utilities (Toast, formatting)
```

## 🔄 Business Logic Details

### Order Placement Flow
1. User adds items to the Cart (checked against vendor distance limits: 2km for retail, 15km for wholesale).
2. User proceeds to checkout, selects delivery location.
3. System calculates delivery fee based on distance (Haversine formula on backend).
4. User initiates M-Pesa STK Push.
5. App polls the backend for payment confirmation.
6. On success, the order is placed and auto-dispatched to a rider.

### Tracking Flow
When an order status is `picked_up`, the app connects to `/ws/track/{order_id}` on the backend to receive live coordinates from the rider. The `react-native-maps` component smoothly animates the rider's marker to the new coordinates.
