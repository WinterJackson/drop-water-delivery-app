import { View, Image } from "react-native";
import { Text } from '@/components/ui/Text';
import React from "react";
import images from "@/constants/images/images";
import Button from "../ui/Button";
import { PressableScale } from "@/components/ui/PressableScale";
import { Ionicons } from "@expo/vector-icons";
import { BRAND } from "../../constants/brandColors";

type Props = {
  data?: any;
};

const TrackOrderCard = ({ data }: Props) => {
  return (
    <View className="bg-gray-100 rounded-xl gap-2 px-4 py-3">
        
      
      {/* <------RIDER PROFILE DETAILES: [ Profile-pic, Plate-No, Rating, Delivery-fee, Phone-number ]-------> */}
      <View className="items-center flex-row gap-4">
        <View className="items-center">
            <View className="w-[70px] h-[70px]">
            <Image
                className="w-full h-full rounded-full border border-gray-200"
                resizeMode="cover"
                source={images.profile_placeholder}
            />
            </View>
            <Text className={"text-lg"}>{`${"John Doe"}`}</Text>
        </View>
        <View className=" w-full gap-1 ">
          {/* <---------RATING----------> */}
          <View className="gap-1">
            <View className="flex-row gap-3 items-end">
              <Text className="font-sans-semibold">Rating:</Text>
              <View className="flex-row gap-1">
                {[...Array(5)].map((star, index) => {
                  return <Text key={index}>⭐</Text>;
                })}
              </View>
              <Text className={"text-gray-500"}>{`${4.7}`}</Text>
            </View>
          </View>
          {/* <---------PLATE_NO----------> */}
          <View className="gap-1">
            <View className="flex-row gap-3 items-end">
              <Text className="font-sans-semibold">Plate No:</Text>
              <Text className={"text-gray-500"}>{`${"KMDC 2485Q"}`}</Text>
            </View>
          </View>
          {/* <---------DELIVERY_FEE----------> */}
          <View className="gap-1">
            <View className="flex-row gap-3 items-end">
              <Text className="font-sans-semibold">Delivery Fee:</Text>
              <Text className={"text-gray-500"}>{`KSH ${120}`}</Text>
            </View>
          </View>
          {/* <---------PHONE_NO----------> */}
          <View className="gap-1">
            <View className="flex-row gap-3 items-center">
              {/* <Text className="font-sans-semibold">Contact:</Text> */}
              <PressableScale 
                activeOpacity={0.7}
                className="flex-row gap-3 items-center"
              >
                <View className="w-10 h-10 shadow-lg shadow-black bg-green-500 rounded-2xl items-center justify-center">
                    <Ionicons name="call" size={24} color={BRAND.white} />
                </View>
                <Text className={"text-gray-500"}>{`${"0742380802"}`}</Text>
              </PressableScale>
            </View>
          </View>
        </View>
      </View>

      <View className="gap-1">
            <View className="gap-1 flex-row items-end">
                <Text className="font-sans-bold text-gray-800">Placed At:  </Text>
                <Text className={'text-gray-700'}>{`${"2:00pm "}`}</Text>
            </View>
            <View className="gap-1 flex-row items-end">
                <Text className="font-sans-bold text-gray-800">Delivery Time:  </Text>
                <Text className={'text-gray-700'}>{`${"10min"}`}</Text>
            </View>
            <View className="gap-1 flex-row items-end">
                <Text className="font-sans-bold text-gray-800">Items:  </Text>
                <Text className={'text-gray-700'}>{`${"3 items"}`}</Text>
            </View>
            <View className="gap-1 flex-row items-end">
                <Text className="font-sans-bold text-gray-800">Amount:  </Text>
                <Text className={'text-gray-700'}>{`KSH ${300}`}</Text>
            </View>
        </View>

        <View className="flex-row">
            <Button style={"px-[50px] rounded-lg"} label={"View Items"} type={"outlin"} textStyle={"text-gray-500"}/>
        </View>

      {/* <------TIME ORDER PLACED-------> */}
      <View className="flex-row absolute self-end bottom-2 right-2">
        <Text className={" text-gray-500"}>{`${"5min ago"}`}</Text>
      </View>
    </View>
  );
};

export default TrackOrderCard;
