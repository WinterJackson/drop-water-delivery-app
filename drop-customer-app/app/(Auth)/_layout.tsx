// import { useAuth } from "@clerk/clek-expo";
import { useApiClient } from "@/API/useApiClient";
import { BRAND } from "@/constants/brandColors";
import { UIThemeContext } from "@/context/ThemeContext";
import { useCreateUser, useUpdateLocation } from "@/hooks/queries/useUser";
import { useLocation } from "@/hooks/useLocation";
import { useAuth, useUser } from '@clerk/clerk-expo';
import { Stack, useRouter } from "expo-router";
import * as WebBrowser from 'expo-web-browser';
import { useContext, useEffect, useState } from "react";
import { PressableScale } from "@/components/ui/PressableScale";
import { Ionicons } from "@expo/vector-icons";
import {
    Dimensions,
    Image,
    Modal,
    StatusBar,
    View,
} from "react-native";
import { Text } from '@/components/ui/Text';
// import Modal from "react-native-modal";

const { width, height } = Dimensions.get("window");

export const useWarmUpBrowser = () => {
  useEffect(() => {
    // Preloads the browser for Android devices to reduce authentication load time
    // See: https://docs.expo.dev/guides/authentication/#improving-user-experience
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
  // <------------------------HOOKES------------------------->
  const { isSignedIn , getToken } = useAuth()
  const router = useRouter();
  const { currentTheme } = useContext(UIThemeContext);
	const { user } = useUser()

  // <------------------------STATES------------------------->
	const { location, showPrompt, requestLocation, loading: locLoading } = useLocation();
    const apiClient = useApiClient();
	const [AuthLoading, setAuthLoading] = useState(false);

	const darkTheme = currentTheme === "dark";

  // <-----------------------VARIABLES----------------------->
  const statusbarHieght = StatusBar.currentHeight || 50;

  // <-----------------------FUNCTIONS----------------------->
  useWarmUpBrowser()

  return (
    <>
      <StatusBar
        translucent={true}
        backgroundColor="transparent"
        barStyle="dark-content" // or "dark-content" depending on your UI
        animated={true}
      />

      <View
        className={`absolute ${darkTheme? 'bg-black' : ''}`}
        style={{
          minHeight: height+statusbarHieght,
          minWidth: width,
        }}
      >
        <Stack
          screenOptions={{
            headerShown: false,
            animation: 'slide_from_right', // Options: 'fade', 'slide_from_right', 'slide_from_left', 'none'
        }}
        />
        {/* loading modal */}
        <Modal visible={AuthLoading}>
					<View className="items-center">
						<View className={""}>
							<Ionicons name="sync" size={24} color={BRAND.gold} />
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
