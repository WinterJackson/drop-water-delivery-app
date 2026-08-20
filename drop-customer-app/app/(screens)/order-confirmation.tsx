/**
 * The screen a customer lands on straight after paying.
 *
 * It used to announce "🎉 Drop Cashback Earned!" on every order,
 * unconditionally. `loyalty_cashback_per_delivery` is a **withdrawn** setting
 * that defaults to 0, and `deliverer_service` credits it only `if cashback >
 * 0`, so nothing has been earned — the platform stopped paying it precisely
 * because paying on every order bought nothing. It is also credited on
 * *delivery*, so even with the setting turned back on there would be nothing
 * to celebrate at the moment of payment. An app must not state a money rule
 * the platform does not implement.
 *
 * `orderId` was also read here and discarded, and neither checkout path passed
 * it — the cash branch had it on the response and the M-Pesa branch cleared
 * `pendingOrderId` on the line above the push. So "Track Order" could only
 * ever open the whole list.
 */
import { UIThemeContext } from '@/context/ThemeContext';
import { useLocalSearchParams, useRouter } from 'expo-router';
import React, { useContext } from 'react';
import { StatusBar, View } from 'react-native';
import { Text } from '@/components/ui/Text';
import { PressableScale } from "@/components/ui/PressableScale";
import { DropyScene } from '@/components/ui/DropyScene';

export default function OrderConfirmation() {
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === 'dark';
    const router = useRouter();
    const { orderId } = useLocalSearchParams();

    return (
        <View className={`flex-1 items-center justify-center ${darkTheme ? 'bg-black' : 'bg-white'}`}>
            <StatusBar translucent barStyle={darkTheme ? "light-content" : "dark-content"} />
            
            <View className="items-center justify-center px-6 gap-6 w-full mt-10">
                <DropyScene
                    mood="celebrate"
                    title="Order Confirmed!"
                    subtitle="Thank you for your purchase. Your water will be delivered soon!"
                />

                <View className="w-full mt-2">
                    <PressableScale 
                        className="w-full bg-sky-500 py-4 rounded-xl items-center"
                        activeOpacity={0.8}
                        onPress={() =>
                            orderId
                                ? router.push({
                                      pathname: '/(screens)/OrderDetail',
                                      params: { orderId: String(orderId) },
                                  })
                                : router.push('/(screens)/Orders')
                        }
                    >
                        <Text className="text-white font-sans-bold text-lg">Track Order</Text>
                    </PressableScale>

                    <PressableScale 
                        className="w-full py-4 items-center mt-3"
                        activeOpacity={0.8}
                        onPress={() => router.push('/(screens)')}
                    >
                        <Text className={`font-sans-bold text-lg ${darkTheme ? 'text-sky-400' : 'text-sky-500'}`}>
                            Back to Home
                        </Text>
                    </PressableScale>
                </View>
            </View>
        </View>
    );
}
