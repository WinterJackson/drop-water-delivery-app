import { UIThemeContext } from "@/context/ThemeContext";
import { useLocation } from "@/hooks/useLocation";
import { useAuth, useUser } from '@clerk/clerk-expo';
import { Stack, useRouter } from "expo-router";
import * as WebBrowser from 'expo-web-browser';
import { useContext, useEffect, useState } from "react";
import { PressableScale } from "@/components/ui/PressableScale";
import {
    Dimensions,
    Image,
    Modal,
    StatusBar,
    View,
    ActivityIndicator,
} from "react-native";
import { Text } from '@/components/ui/Text';
import { BRAND } from "@/constants/brandColors";
import { Ionicons } from "@expo/vector-icons";

const { width, height } = Dimensions.get("window");

export const useWarmUpBrowser = () => {
  useEffect(() => {
    // Preloads the browser for Android devices to reduce authentication load time
    void WebBrowser.warmUpAsync()
    return () => {
      // Cleanup: closes browser when component unmounts
      void WebBrowser.coolDownAsync()
    }
  }, [])
}

// Handle any pending authentication sessions
WebBrowser.maybeCompleteAuthSession()

const Layout = () => {
  const { isSignedIn , getToken } = useAuth()
  const router = useRouter();
  const { currentTheme } = useContext(UIThemeContext);
  const { user } = useUser()

  const { location, showPrompt, requestLocation, loading: locLoading } = useLocation();
  const [AuthLoading, setAuthLoading] = useState(false);

  const darkTheme = currentTheme === "dark";

  const statusbarHieght = StatusBar.currentHeight || 50;

  useWarmUpBrowser()

  return (
    <>
      <StatusBar
        translucent={true}
        backgroundColor="transparent"
        barStyle="dark-content"
        animated={true}
      />

      <View
        className={`absolute ${darkTheme? 'bg-black' : 'bg-white'}`}
        style={{
          minHeight: height+statusbarHieght,
          minWidth: width,
        }}
      >
        <Stack
          screenOptions={{
            headerShown: false,
            animation: 'slide_from_right',
        }}
        />
        {/* loading modal */}
        <Modal visible={AuthLoading} transparent={true} animationType="fade">
					<View className="flex-1 items-center justify-center bg-black/50">
						<View className="bg-white p-6 rounded-2xl items-center shadow-xl">
							<ActivityIndicator size="large" color={BRAND.primary} />
						</View>
					</View>
				</Modal>

        {/* location access prompt modal */}
        <Modal visible={showPrompt} transparent={true} animationType="fade">
						<View className="items-center flex-1 justify-center">
							<View
								className={`bg-white w-[80%]  gap-6 max-w-[300px] rounded-3xl p-6`}
							>
								<View className={`flex-row gap-3 `}>
									<Ionicons name="locate" size={24} color={BRAND.primary} />
									<Text className="font-heading-semibold text-2xl text-blue-500">
										Location Access
									</Text>
								</View>
								<View className="">
									<View className="">
										<Text>
											This app requires access to your
											current location for it to work
											properly.{" "}
										</Text>
										<Text>
											Please grant permission to access
											your location in order to proceed
										</Text>
										<Text>
											If you have allowed location
											permission and are still getting
											this prompt it might be a Network
											issue so Please check your Network
											settings{" "}
										</Text>
									</View>
								</View>
								<PressableScale
									activeOpacity={0.8}
									onPress={() => {
										requestLocation();
									}}
								>
									<View
										className={`bg-blue-500 p-3 px-6 rounded-xl items-center `}
									>
										<Text
											className={`text-white font-sans-bold`}
										>
											Allow Location Access
										</Text>
									</View>
								</PressableScale>
							</View>
						</View>
				</Modal>
      </View>
    </>
  );
};

export default Layout;
