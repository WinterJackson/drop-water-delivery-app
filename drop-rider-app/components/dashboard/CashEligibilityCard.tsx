import { Ionicons } from "@expo/vector-icons";
import React, { useContext } from "react";
import { View } from "react-native";
import { Text } from '@/components/ui/Text';

import { BRAND } from "@/constants/brandColors";
import { UIThemeContext } from "@/context/ThemeContext";
import { useCashEligibility, type CashRequirement } from "@/hooks/queries/useWallet";
import { formatMoneyShort, moneyRatio } from "@/utils/money";

/**
 * Whether this rider can take cash orders, and what stands between them and it.
 *
 * The float check only ever asked whether a rider could *cover* a cash order.
 * Six other things decide whether they should be carrying somebody else's money
 * at all, and until this screen existed none of them was visible: a rider saw
 * cash orders in the radar, tapped, and was refused — with no way to tell a
 * temporary limit from a permanent one, or to know what to do about either.
 *
 * Every figure here is measured against the requirement the server applied.
 * Restating any of them as a literal would let the console change what a rider
 * is judged by without changing what they are told, which is the same defect
 * `Cashout.tsx` had with the withdrawal fee.
 */
export function CashEligibilityCard() {
  const { currentTheme } = useContext(UIThemeContext);
  const dark = currentTheme === "dark";
  const { data } = useCashEligibility();

  if (!data || !data.cash_enabled_on_platform) return null;

  const card = `p-4 rounded-2xl mb-3 ${dark ? "bg-surface-container" : "bg-white"}`;

  // ── Already eligible: show the headroom, not the criteria ──
  if (data.eligible) {
    const { carrying_now, max_concurrent, taken_today, daily_cap } = data.limits;
    const atOrderCap = carrying_now >= max_concurrent;
    // Money is compared in cents, never as a float — `moneyRatio` is the one
    // sanctioned conversion and its output is a threshold, not a figure.
    const nearMoneyCap = moneyRatio(taken_today, daily_cap) >= 0.8;

    return (
      <View className={card}>
        <View className="flex-row items-center justify-between">
          <View className="flex-row items-center gap-2">
            <Ionicons name="cash-outline" size={18} color={BRAND.primary} />
            <Text className={`font-sans-bold ${dark ? "text-white" : "text-slate-900"}`}>
              Cash orders open
            </Text>
          </View>
          {data.tier === "platinum" ? (
            <Text className="text-xs font-sans-bold" style={{ color: BRAND.primary }}>
              PLATINUM
            </Text>
          ) : null}
        </View>

        <Text className={`text-xs mt-1 ${dark ? "text-gray-400" : "text-slate-500"}`}>
          Up to {formatMoneyShort(data.max_order_value)} per order
          {data.tier === "standard" ? " — Platinum riders can carry more." : "."}
        </Text>

        <View className="flex-row gap-3 mt-3">
          <Limit
            label="Carrying now"
            value={`${carrying_now} of ${max_concurrent}`}
            warn={atOrderCap}
            dark={dark}
          />
          <Limit
            label="Cash today"
            value={`${formatMoneyShort(taken_today)} of ${formatMoneyShort(daily_cap, "")}`}
            warn={nearMoneyCap}
            dark={dark}
          />
        </View>

        {atOrderCap ? (
          <Text className={`text-xs mt-3 ${dark ? "text-amber-400" : "text-amber-700"}`}>
            You are at your cash-order limit. Deliver one and this opens up again —
            M-Pesa orders are unaffected.
          </Text>
        ) : null}
      </View>
    );
  }

  // ── Not eligible: the requirements, with progress against each ──
  const { deliveries, completion_rate, rating, account_age_days } = data.requirements;

  return (
    <View className={card}>
      <View className="flex-row items-center gap-2">
        <Ionicons name="lock-closed-outline" size={18} color={dark ? "#94A3B8" : "#64748B"} />
        <Text className={`font-sans-bold ${dark ? "text-white" : "text-slate-900"}`}>
          Cash orders not open yet
        </Text>
      </View>
      <Text className={`text-xs mt-1 mb-3 ${dark ? "text-gray-400" : "text-slate-500"}`}>
        Carrying a customer&apos;s cash is the one job where the platform cannot
        undo a mistake, so it opens up once these are met.
      </Text>

      <Progress label="Deliveries completed" req={deliveries} dark={dark} />
      <Progress
        label="Completion rate"
        req={completion_rate}
        dark={dark}
        format={(n) => `${Math.round(n * 100)}%`}
      />
      <Progress label="Rating" req={rating} dark={dark} format={(n) => n.toFixed(1)} />
      <Progress
        label="Days on the platform"
        req={account_age_days}
        dark={dark}
        format={(n) => `${Math.round(n)}`}
      />

      {/* Anything the requirements above cannot express — verification, a
          suspension — arrives as a sentence from the server rather than being
          inferred here. */}
      {data.reasons
        .filter((r) => !/deliveries|completion|rating|days on the platform/i.test(r))
        .map((reason) => (
          <Text
            key={reason}
            className={`text-xs mt-2 ${dark ? "text-amber-400" : "text-amber-700"}`}
          >
            {reason}
          </Text>
        ))}
    </View>
  );
}

function Progress({
  label,
  req,
  dark,
  format = (n: number) => `${Math.round(n)}`,
}: {
  label: string;
  req: CashRequirement;
  dark: boolean;
  format?: (n: number) => string;
}) {
  const met = req.have >= req.need;
  const pct = req.need > 0 ? Math.min(1, req.have / req.need) : 1;

  return (
    <View className="mb-2.5">
      <View className="flex-row items-center justify-between mb-1">
        <View className="flex-row items-center gap-1.5">
          <Ionicons
            name={met ? "checkmark-circle" : "ellipse-outline"}
            size={14}
            color={met ? BRAND.primary : dark ? "#475569" : "#CBD5E1"}
          />
          <Text className={`text-xs ${dark ? "text-gray-300" : "text-slate-600"}`}>{label}</Text>
        </View>
        <Text
          className={`text-xs font-sans-medium ${
            met ? "" : dark ? "text-gray-400" : "text-slate-500"
          }`}
          style={met ? { color: BRAND.primary } : undefined}
        >
          {format(req.have)} / {format(req.need)}
        </Text>
      </View>
      <View className={`h-1.5 rounded-full ${dark ? "bg-slate-800" : "bg-slate-100"}`}>
        <View
          className="h-1.5 rounded-full"
          style={{ width: `${pct * 100}%`, backgroundColor: BRAND.primary }}
        />
      </View>
    </View>
  );
}

function Limit({
  label,
  value,
  warn,
  dark,
}: {
  label: string;
  value: string;
  warn: boolean;
  dark: boolean;
}) {
  return (
    <View className={`flex-1 px-3 py-2 rounded-xl ${dark ? "bg-slate-800/60" : "bg-slate-50"}`}>
      <Text className={`text-[10px] ${dark ? "text-gray-500" : "text-slate-400"}`}>{label}</Text>
      <Text
        className={`text-sm font-sans-bold mt-0.5 ${
          warn ? (dark ? "text-amber-400" : "text-amber-700") : dark ? "text-white" : "text-slate-900"
        }`}
      >
        {value}
      </Text>
    </View>
  );
}
