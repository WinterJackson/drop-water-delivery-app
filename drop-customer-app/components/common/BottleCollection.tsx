import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import React, { useContext, useEffect, useState } from "react";
import { ActivityIndicator, View } from "react-native";
import { Text } from '@/components/ui/Text';

import { errorMessage } from "@/API/errors";
import { PressableScale } from "@/components/ui/PressableScale";
import { BRAND } from "@/constants/brandColors";
import { UIThemeContext } from "@/context/ThemeContext";
import {
  useBookBottleCollection,
  useCancelBottleCollection,
  useConfirmBottleHandover,
  type BottleCollection as Collection,
} from "@/hooks/queries/useBottleDeposit";
import { Popup } from "@/lib/popup";
import { Toast } from "@/lib/toast";
import { formatMoney } from "@/utils/money";

/**
 * Getting the deposit back.
 *
 * The screen above this already told the customer "return the bottles on your
 * next refill and this comes back to your wallet" — a promise with nothing
 * behind it. The only path back was an administrator opening the console under
 * a permission no preset but super admin holds, so a deposit was refundable in
 * principle and unreturnable in fact, which makes it a price.
 *
 * **Two counts, and they must agree.** The rider states what they collected and
 * the customer states what they handed over. Agreement returns the deposit
 * immediately; a disagreement goes to a human and nothing moves. So this asks
 * for the number explicitly rather than assuming what was booked — the figure
 * entered here is the one the money follows.
 *
 * Every amount shown is the server's. Nothing here computes what a bottle is
 * worth back: that is one function shared with the console and the rider app,
 * because three places quoting different figures for one handover is a dispute
 * the platform cannot win.
 */

type Props = {
  bottlesHeld: number;
  bottleLimit: number;
  notWithdrawable: string;
  openRequest: Collection | null;
};

function Stepper({
  value,
  onChange,
  max,
  dark,
  label,
}: {
  value: number;
  onChange: (next: number) => void;
  max: number;
  dark: boolean;
  label: string;
}) {
  const step = (delta: number) => {
    const next = Math.min(max, Math.max(1, value + delta));
    if (next !== value) {
      Haptics.selectionAsync();
      onChange(next);
    }
  };

  return (
    <View className="flex-row items-center justify-between">
      <Text className={`text-sm ${dark ? "text-slate-300" : "text-slate-600"}`}>{label}</Text>
      <View className="flex-row items-center gap-4">
        <PressableScale
          onPress={() => step(-1)}
          accessibilityRole="button"
          accessibilityLabel="One fewer bottle"
          disabled={value <= 1}
        >
          <View
            className={`w-10 h-10 rounded-full items-center justify-center ${
              dark ? "bg-slate-800" : "bg-slate-100"
            } ${value <= 1 ? "opacity-40" : ""}`}
          >
            <Ionicons name="remove" size={20} color={dark ? "#E2E8F0" : "#0F172A"} />
          </View>
        </PressableScale>

        <Text
          className={`text-2xl font-sans-extrabold w-10 text-center ${dark ? "text-white" : "text-slate-900"}`}
          accessibilityLiveRegion="polite"
        >
          {value}
        </Text>

        <PressableScale
          onPress={() => step(1)}
          accessibilityRole="button"
          accessibilityLabel="One more bottle"
          disabled={value >= max}
        >
          <View
            className={`w-10 h-10 rounded-full items-center justify-center ${
              dark ? "bg-slate-800" : "bg-slate-100"
            } ${value >= max ? "opacity-40" : ""}`}
          >
            <Ionicons name="add" size={20} color={dark ? "#E2E8F0" : "#0F172A"} />
          </View>
        </PressableScale>
      </View>
    </View>
  );
}

export function BottleCollectionCard({
  bottlesHeld,
  bottleLimit,
  notWithdrawable,
  openRequest,
}: Props) {
  const { currentTheme } = useContext(UIThemeContext);
  const dark = currentTheme === "dark";

  const book = useBookBottleCollection();
  const confirm = useConfirmBottleHandover();
  const cancel = useCancelBottleCollection();

  const [count, setCount] = useState(Math.min(1, bottlesHeld) || 1);
  const [handedOver, setHandedOver] = useState(openRequest?.bottles_requested ?? 1);

  // The booked figure is the sensible starting point for "how many did you
  // actually hand over", but only until the customer has an open request to
  // read it from.
  useEffect(() => {
    if (openRequest) setHandedOver(openRequest.bottles_requested || 1);
  }, [openRequest]);

  const card = `p-5 rounded-3xl border mb-4 ${
    dark ? "bg-surface-container border-transparent" : "bg-white border-gray-100"
  }`;

  const restricted = Number(notWithdrawable) || 0;

  // ── Nothing on deposit ────────────────────────────────────────────────
  if (bottlesHeld <= 0 && !openRequest) {
    return restricted > 0 ? <RestrictedNote amount={notWithdrawable} dark={dark} /> : null;
  }

  // ── A collection is already booked ────────────────────────────────────
  if (openRequest) {
    const waitingOnMe = openRequest.bottles_stated_by_customer === null;
    const riderConfirmed = openRequest.bottles_stated_by_rider !== null;

    return (
      <>
        <View className={card}>
          <View className="flex-row items-center gap-2 mb-1">
            <Ionicons name="bicycle-outline" size={18} color={BRAND.primary} />
            <Text className={`font-sans-bold ${dark ? "text-white" : "text-slate-900"}`}>
              {riderConfirmed ? "Your rider has confirmed" : "Collection booked"}
            </Text>
          </View>

          <Text className={`text-xs mb-4 ${dark ? "text-slate-400" : "text-slate-500"}`}>
            {riderConfirmed
              ? "Confirm how many you handed over and the deposit goes straight back to your wallet."
              : `We will collect ${openRequest.bottles_requested} bottle(s). Confirm the count once the rider has them.`}
          </Text>

          {waitingOnMe ? (
            <>
              <Stepper
                value={handedOver}
                onChange={setHandedOver}
                max={Math.max(bottlesHeld, openRequest.bottles_requested)}
                dark={dark}
                label="Bottles I handed over"
              />

              <PressableScale
                onPress={async () => {
                  try {
                    const result = await confirm.mutateAsync({
                      id: openRequest.id,
                      bottles: handedOver,
                    });
                    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
                    if (result.status === "settled") {
                      Toast.success(
                        "Deposit returned",
                        `${formatMoney(result.amount_refunded)} is back in your wallet.`,
                      );
                    } else if (result.status === "disputed") {
                      // Deliberately not framed as an error. Nothing is wrong
                      // with what they did; the two counts differ and a person
                      // is going to look at it.
                      Toast.info("We'll check this", result.detail ?? "Your deposit is safe.");
                    } else {
                      Toast.info("Confirmed", "Waiting for your rider to confirm.");
                    }
                  } catch (err) {
                    Toast.error("Couldn't confirm", errorMessage(err));
                  }
                }}
                disabled={confirm.isPending}
              >
                <View
                  className="mt-4 rounded-2xl py-3.5 items-center justify-center flex-row gap-2"
                  style={{ backgroundColor: BRAND.primary, opacity: confirm.isPending ? 0.6 : 1 }}
                >
                  {confirm.isPending ? (
                    <ActivityIndicator color="#fff" size="small" />
                  ) : (
                    <Ionicons name="checkmark-circle-outline" size={18} color="#fff" />
                  )}
                  <Text className="text-white font-sans-bold">Confirm handover</Text>
                </View>
              </PressableScale>
            </>
          ) : (
            <View
              className={`rounded-2xl px-4 py-3 ${dark ? "bg-slate-800/60" : "bg-slate-50"}`}
            >
              <Text className={`text-xs ${dark ? "text-slate-300" : "text-slate-600"}`}>
                You confirmed {openRequest.bottles_stated_by_customer} bottle(s). Waiting
                for the rider to confirm — your deposit is safe either way.
              </Text>
            </View>
          )}

          {!riderConfirmed ? (
            <PressableScale
              onPress={() => {
                Popup.show({
                  title: "Cancel this collection?",
                  message: "You keep the bottles and the deposit. You can book another any time.",
                  confirmText: "Cancel it",
                  cancelText: "Keep it",
                  isDestructive: true,
                  onConfirm: async () => {
                    try {
                      await cancel.mutateAsync({ id: openRequest.id });
                      Toast.success("Collection cancelled");
                    } catch (err) {
                      Toast.error("Couldn't cancel", errorMessage(err));
                    }
                  },
                });
              }}
            >
              <Text
                className={`text-xs text-center mt-3 ${dark ? "text-slate-500" : "text-slate-400"}`}
              >
                Cancel this collection
              </Text>
            </PressableScale>
          ) : null}
        </View>

        {restricted > 0 ? <RestrictedNote amount={notWithdrawable} dark={dark} /> : null}
      </>
    );
  }

  // ── Book one ──────────────────────────────────────────────────────────
  return (
    <>
      <View className={card}>
        <View className="flex-row items-center gap-2 mb-1">
          <Ionicons name="arrow-undo-outline" size={18} color={BRAND.primary} />
          <Text className={`font-sans-bold ${dark ? "text-white" : "text-slate-900"}`}>
            Get your deposit back
          </Text>
        </View>
        <Text className={`text-xs mb-4 ${dark ? "text-slate-400" : "text-slate-500"}`}>
          A rider collects the bottles and the deposit returns to your wallet as
          soon as you both confirm the count. You are holding {bottlesHeld} of a
          maximum {bottleLimit}.
        </Text>

        <Stepper
          value={count}
          onChange={setCount}
          max={bottlesHeld}
          dark={dark}
          label="Bottles to collect"
        />

        <PressableScale
          onPress={async () => {
            try {
              await book.mutateAsync({ bottles: count });
              Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
              Toast.success("Collection booked", "A rider will pick these up.");
            } catch (err) {
              Toast.error("Couldn't book that", errorMessage(err));
            }
          }}
          disabled={book.isPending}
        >
          <View
            className="mt-4 rounded-2xl py-3.5 items-center justify-center flex-row gap-2"
            style={{ backgroundColor: BRAND.primary, opacity: book.isPending ? 0.6 : 1 }}
          >
            {book.isPending ? (
              <ActivityIndicator color="#fff" size="small" />
            ) : (
              <Ionicons name="bicycle-outline" size={18} color="#fff" />
            )}
            <Text className="text-white font-sans-bold">Book a collection</Text>
          </View>
        </PressableScale>
      </View>

      {restricted > 0 ? <RestrictedNote amount={notWithdrawable} dark={dark} /> : null}
    </>
  );
}

/**
 * Money that spends and does not cash out.
 *
 * Stated here rather than discovered at the withdrawal form. A returned deposit
 * is credited as wallet balance the customer can spend on any order but cannot
 * withdraw — otherwise the deposit is a money-transfer service. That is a real
 * condition on their money and they are entitled to know before they rely on it.
 */
function RestrictedNote({ amount, dark }: { amount: string; dark: boolean }) {
  return (
    <View
      className={`p-4 rounded-3xl border mb-4 ${
        dark ? "bg-slate-800/40 border-slate-700" : "bg-slate-50 border-slate-200"
      }`}
    >
      <View className="flex-row items-start gap-3">
        <Ionicons
          name="information-circle-outline"
          size={18}
          color={dark ? "#94A3B8" : "#64748B"}
        />
        <Text className={`flex-1 text-xs ${dark ? "text-slate-300" : "text-slate-600"}`}>
          <Text className="font-sans-bold">{formatMoney(amount)}</Text> of your balance is returned
          bottle deposit. Spend it on any order — it just cannot be withdrawn as cash.
        </Text>
      </View>
    </View>
  );
}
