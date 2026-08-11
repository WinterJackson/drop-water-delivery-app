import images from '@/constants/images/images'
import { UIThemeContext } from '@/context/ThemeContext'
import { useContext } from 'react'
import { Image, View } from 'react-native';
import { Text } from '@/components/ui/Text';import { PressableScale } from "@/components/ui/PressableScale";

type Props = {
  data? : any
  TrackOrder: () => void
}

const OngoingOrderCard = ({data, TrackOrder}: Props) => {
  const { currentTheme } = useContext(UIThemeContext);
	const darkTheme = currentTheme === "dark";
  return (
    <View className={`w-full max-w-[400px]  bg-accentbg/20 p-5 rounded-2xl overflow-hidden `}>
      <View className={`min-h-[150px] min-w-[500px] bg-accentbg rotate-[30deg] absolute bottom-0 -left-7`}/>
      <View className={`w-[200px] h-[200px] absolute -bottom-3 right-0`}>
        <Image source={images.ongoing_delivery} className={`w-full h-full`}/>
      </View>
      <Text className={`${darkTheme ? "text-gray-300" : ""}`}>Order ID </Text>
      <View className={`gap-4`}>
        <Text className={`font-sans-bold text-lg`}>#{data?.id || "N/A"}</Text>
        <View className={`flex-row`}>
          <PressableScale
            activeOpacity={0.7}
            onPress={()=>{TrackOrder()}}
          >
            <View className={`px-6 py-2 ${darkTheme?"bg-white":"bg-black"} rounded-full w-fit`}>
              <Text className={`text-accentbg text-lg font-sans-bold`}>Track Order</Text>
            </View>
          </PressableScale>
        </View>
        <View>
          <Text className={`font-sans-bold ${darkTheme?"text-gray-300":""}`}>Picked From the Vendor</Text>
          <Text className={`${darkTheme?"text-gray-300":""}`}>{data?.created_at ? new Date(data.created_at).toLocaleString() : "Unknown Time"}</Text>
        </View>
      </View>
    </View>
  )
}

export default OngoingOrderCard