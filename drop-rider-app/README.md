# Drop Rider App 🛵

> The delivery agent application for the Drop Multivendor Water Delivery Platform. Built with Expo, React Native, and Tailwind CSS (NativeWind).

## 📱 Overview

The Drop Rider App empowers delivery personnel to find work, fulfill water orders efficiently, manage empty bottles, and track their daily earnings. It serves both independent gig riders and in-house fleet riders.

### Core Features
- **Trip Radar**: A real-time dispatch screen showing nearby available orders with expected payouts and distances.
- **Active Delivery**: A focused, distraction-free screen guiding the rider through the pickup and drop-off process using integrated mapping.
- **Live Tracking**: Broadcasts the rider's GPS location via WebSockets to the customer during active deliveries.
- **Proof of Delivery**: Mandatory photo capture to verify successful drop-offs or to document bottle rejections.
- **Empty Bottle Management**: A structured workflow for picking up empty bottles from customers and reconciling them with vendors.
- **Earnings Dashboard**: A transparent ledger of all completed trips, base pay, tips, and deductions.

## 🛠️ Tech Stack

- **Framework**: React Native with [Expo SDK 54](https://expo.dev/)
- **Routing**: [Expo Router](https://docs.expo.dev/router/introduction/) (File-based routing)
- **Styling**: [NativeWind v4](https://www.nativewind.dev/) (Tailwind CSS)
- **State Management**: [Zustand](https://zustand-demo.pmnd.rs/) & [TanStack Query v5](https://tanstack.com/query/latest)
- **Authentication**: [Clerk](https://clerk.com/) (Email, Phone OTP, OAuth)
- **Real-time**: `socket.io-client` for WebSockets (Order Updates & GPS Broadcasting)
- **Background Location**: `expo-location` (Foreground tracking via WebSocket, background tracking via REST API)
- **Maps & Routing**: `react-native-maps`

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
   # Info.plist, not the JS bundle. One key per platform, because a Google API
   # key can carry only one application restriction.
   GOOGLE_MAPS_ANDROID_API_KEY=...   # restricted to com.drop.rider + SHA-1
   GOOGLE_MAPS_IOS_API_KEY=...       # restricted to bundle id com.drop.rider
   ```

3. Run the app:
   ```bash
   pnpm start
   ```

## 📂 Project Structure

```
drop-rider-app/
├── app/
│   ├── (Auth)/           # Authentication and KYC Onboarding
│   ├── (screens)/        # Core app screens (Radar, Active, Earnings)
│   └── _layout.tsx       # Root layout
├── API/
│   └── routes/           # Strictly typed Rider API definitions
├── components/
│   ├── delivery/         # Map overlays, swipe-to-complete buttons
│   ├── radar/            # Trip radar cards
│   └── ui/               # Base UI elements
├── constants/            # Theme, images, icons
├── context/              # Context providers (LocationContext)
├── hooks/
│   └── queries/          # TanStack Query data fetching
└── lib/                  # Utilities (Toast, Location formatting)
```

## 🔄 Business Logic Details

### Dispatch & Trip Radar
When an order is created, if a vendor doesn't have an in-house rider available, it hits the "Trip Radar". 
1. Backend finds all online gig riders within the search radius (2km for retail).
2. Broadcasts the order via WebSockets to those riders.
3. The first rider to swipe "Accept" claims the order (handled via atomic database row-locking on the backend to prevent race conditions).

### Delivery Workflow & Bottle Rejection
1. Rider navigates to Vendor, taps "Confirm Pickup".
2. Rider navigates to Customer.
3. If the customer is returning empty bottles (a "Quick Swap" order), the rider must verify the bottle count.
4. **Dispute**: If the customer promised 4 bottles but only has 2, the rider flags a "Bottle Mismatch". They take a photo of the 2 bottles as proof. The order goes into `pending_review` and a background worker handles the financial adjustment.
5. If everything is correct, the rider takes a Proof of Delivery photo and swipes to complete. Status shifts to `delivered`.

### Background GPS Tracking
During an active delivery, the app watches the device's location.
- **WebSocket (Primary)**: Broadcasts `{ lat, lng, speed, heading }` to `/ws/rider/{rider_id}` every few seconds for smooth customer viewing.
- **REST Fallback**: If the app is backgrounded, a background task periodically posts to `POST /api/rider/location`.
