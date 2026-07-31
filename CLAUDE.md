# Drop Multivendor Water Delivery Platform — Developer Guide

This file contains instructions and context for AI coding assistants working on the Drop platform.

## Architecture & Monorepo Structure
This is a monorepo containing three React Native Expo applications and one FastAPI backend:
- `BackendAPI/`: Python FastAPI backend.
- `drop-customer-app/`: Expo React Native app for customers.
- `drop-rider-app/`: Expo React Native app for delivery riders.
- `drop-vendor-app/`: Expo React Native app for water vendors.

## Coding Conventions
### Backend (FastAPI / Python)
- Use standard Python typing and Pydantic models (v2).
- Follow a modular architecture: `routes/`, `services/`, `models/`, `schemas/`.
- Use `geoalchemy2` for PostGIS location queries.
- WebSocket interactions (`socket.io` equivalent) are handled in `websocket_routes.py` and `order_service.py`.
- Background tasks are in `worker.py` (ARQ).

### Frontend (React Native / Expo)
- **Styling**: NativeWind (Tailwind CSS for React Native).
- **State Management**: React Query (`@tanstack/react-query`) for server state, Zustand for client state.
- **Routing**: Expo Router (file-based).
- **Data Fetching**: Custom hooks abstracting React Query (e.g., `useRiderData.ts`). DO NOT fetch directly inside components.
- **Error Handling**: Use the global `Toast.error` component to display user-friendly backend errors. DO NOT silently fail or throw raw HTTP status codes to users.

## Common Tasks & Commands

### Backend
```bash
cd BackendAPI
source venv/bin/activate
uvicorn main:app --reload
```

### Expo Apps
```bash
cd drop-rider-app # or vendor/customer
pnpm install
npx tsc --noEmit # to verify type safety
expo start
```

## Security & Guardrails
- **Proof of Delivery**: Any order completion (`delivered`) requires a deficit check. If there are missing bottles (`emptiesReceived < computedEmptiesExpected`), a photo proof is strictly mandatory. DO NOT bypass this check in `catch` blocks.
- **KYC**: Rider onboarding requires KYC approval by an Admin. They remain blocked in `VerificationWall` until `kyc_status == "approved"`.
