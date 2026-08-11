import { UIThemeContext } from '@/context/ThemeContext';
import { useLocalSearchParams, useRouter } from 'expo-router';
import React, { useContext } from 'react';
import { StatusBar, View } from 'react-native';
import { Text } from '@/components/ui/Text';
import { PressableScale } from "@/components/ui/PressableScale";
import Animated, { BounceIn } from 'react-native-reanimated';
import { TOAST } from "@/constants/brandColors";
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

                <Animated.View 
                    entering={BounceIn.delay(800)}
                    className={`px-5 py-3 rounded-full border ${darkTheme ? 'bg-green-500/20 border-green-500/30' : 'bg-green-50 border-green-200'}`}
                >
                    <Text className="font-sans-bold text-base text-center" style={{ color: TOAST.success }}>
                        🎉 Drop Cashback Earned!
                    </Text>
                </Animated.View>

                <View className="w-full mt-2">
                    <PressableScale 
                        className="w-full bg-sky-500 py-4 rounded-xl items-center"
                        activeOpacity={0.8}
                        onPress={() => router.push('/(screens)/Orders')}
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
