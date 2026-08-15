import { UIThemeContext } from "@/context/ThemeContext";
import { useRouter } from "expo-router";
import React, { useContext } from "react";
import { Dimensions, Image, View } from "react-native";
import { Text } from '@/components/ui/Text';
import DropButton from "../ui/DropButton";
import { PressableScale } from "@/components/ui/PressableScale";
import { Ionicons } from "@expo/vector-icons";

import type { GeoJSONVendorProperties } from "@/types/models";

const { width } = Dimensions.get("window");

/**
 * `data` is a **map marker's** properties, not a `Vendor` — the map screen
 * builds `{id, title, rating, image}` from one before setting it. This file
 * used to carry its own `Vendor` declaration, unused and still listing
 * `verification_status` and `preferred_payment_method`, which the server
 * stopped sending customers; `data: any` is what let a dead type sit beside a
 * prop it did not describe.
 */
type Props = {
	data?: GeoJSONVendorProperties;
	FullMap: boolean;
	// partialMap: () => void
};

const MiniVendorCard = ({ data, FullMap }: Props) => {
	// <--------------------HOOKS-------------------->
	const router = useRouter();
	const { currentTheme } = useContext(UIThemeContext);
	const darkTheme = currentTheme === "dark";
	// console.log(data)

  if(data === undefined){
    return
  }
	return (
		<View
			className={`${darkTheme?"bg-black":"bg-white"} w-full gap-3 p-5 items-center rounded-[24px] shadow-sm border border-gray-200/20`}
			style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
		>
			<View className={`flex-row gap-4 items-start`}>
        {/* profilpic */}
        <View className={`w-[60px] h-[60px] rounded-full overflow-hidden relative`}>
          <Ionicons name="person" size={24} color={darkTheme?"gray":"dimgray"} />
          {data.image && (
            <Image source={{uri: data.image}} className="w-full h-full rounded-full absolute" />
          )}
        </View>
        {/* details */}
        <View className={`gap-1 flex-1 `}>
          <Text className={`font-sans-bold text-lg ${darkTheme?"text-white":"text-black"}`} numberOfLines={1} ellipsizeMode="tail">{data.title}</Text>

          {/* <----------------WHERE IT IS--------------->
              The owner's personal name used to sit here, labelled "Vendor:".
              That is the shopkeeper's own name on a card shown to every
              customer browsing, and the server no longer sends it. Where the
              shop actually is, is both non-identifying and the thing a customer
              is looking for. */}
          <View className="gap-1 flex-row items-center">
            <Ionicons name="location-outline" size={14} color={darkTheme ? "#cbd5e1" : "#475569"} />
            <Text className={`${darkTheme?"text-gray-300":"text-gray-700"} flex-1 font-sans-semibold`} numberOfLines={1} ellipsizeMode="tail">
              {data?.location_address ?? "Location not set"}
            </Text>
          </View>

          {/* <-----------------RATING------------------>
              `rating` is null on a store nobody has reviewed yet, and
              `Array(Math.round(null))` is `Array(NaN)`, which **throws**
              "Invalid array length" — so tapping a new shop on the map crashed
              this card. A store with no rating says so instead. */}
          <View className="flex-row items-center gap-3">
            <Text className={`font-sans-bold ${darkTheme? "text-white":"text-black"}`}>Rating:</Text>
            {data.rating == null ? (
              <Text className={`${darkTheme?"text-gray-400":"text-gray-500"}`}>Not rated yet</Text>
            ) : (
              <>
                <View className="flex-row gap-1">
                  {Array.from({ length: Math.round(data.rating) }).map((_, index) => (
                    <Text key={index}>⭐</Text>
                  ))}
                </View>
                <View className="pl-3 flex-row gap-3 text-gray-500 items-end">
                  <Text>/</Text>
                  <Text className={`${darkTheme?"text-gray-400":"text-gray-500"}`}>{`${data.rating}`}</Text>
                </View>
              </>
            )}
          </View>

          {/* <------------FULL RATING STATS------------> */}
          
          {/* <--------------EST DISTANCE---------------> */}
          {/* <View className=" flex-row gap-2 items-end">
            <Text className={`font-sans-bold ${darkTheme? "text-white":"text-black"}`}>Delivery Time:</Text>
            <Text className={`${darkTheme?"text-white":"text-black"}>{`${"45min"}</Text>
          </View> */}
        </View>
      </View>

			{/* <-----------VIEW VENDOR BUTTON------------> */}
			<DropButton
				onPress={() => {
					router.push(`/(screens)/vendor/${data.id}`);
				}}
				title="View Products"
				style="w-full mt-2"
				textStyle={`${darkTheme?"text-black":"text-white"}`}
			/>
		</View>
	);
};

export default MiniVendorCard;

// {!FullMap && (
// 	<View>
// 		{/* one star */}
// 		<View
// 			className="flex-row gap-3 items-center "
// 			style={{
// 				maxWidth: width * 0.8,
// 			}}
// 		>
// 			<View className=" py-1">
// 				<Text className={`font-sans-bold text-lg ${darkTheme? "text-white":"text-black"}`}>
// 					1 star :{"  "}
// 				</Text>
// 			</View>
// 			<View className="flex-1 h-3 justify-end ">
// 				<PercentageBar
// 					percentage={3}
// 					width={width * 0.65}
// 				/>
// 			</View>
// 		</View>
// 		{/* two star */}

// 		<View
// 			className="flex-row gap-3 items-center "
// 			style={{
// 				maxWidth: width * 0.8,
// 			}}
// 		>
// 			<View className=" py-1">
// 				<Text className={`font-sans-bold text-lg ${darkTheme? "text-white":"text-black"}`}>
// 					2 stars :
// 				</Text>
// 			</View>
// 			<View className="flex-1 h-3 justify-end ">
// 				<PercentageBar
// 					percentage={20}
// 					width={width * 0.65}
// 				/>
// 			</View>
// 		</View>
// 		{/* three star */}

// 		<View
// 			className="flex-row gap-3 items-center "
// 			style={{
// 				maxWidth: width * 0.8,
// 			}}
// 		>
// 			<View className=" py-1">
// 				<Text className={`font-sans-bold text-lg ${darkTheme? "text-white":"text-black"}`}>
// 					3 stars :
// 				</Text>
// 			</View>
// 			<View className="flex-1 h-3 justify-end ">
// 				<PercentageBar
// 					percentage={14}
// 					width={width * 0.65}
// 				/>
// 			</View>
// 		</View>
// 		{/* four star */}

// 		<View
// 			className="flex-row gap-3 items-center "
// 			style={{
// 				maxWidth: width * 0.8,
// 			}}
// 		>
// 			<View className=" py-1">
// 				<Text className={`font-sans-bold text-lg ${darkTheme? "text-white":"text-black"}`}>
// 					4 stars :
// 				</Text>
// 			</View>
// 			<View className="flex-1 h-3 justify-end ">
// 				<PercentageBar
// 					percentage={31}
// 					width={width * 0.65}
// 				/>
// 			</View>
// 		</View>
// 		{/* five star */}

// 		<View
// 			className="flex-row gap-3 items-center "
// 			style={{
// 				maxWidth: width * 0.8,
// 			}}
// 		>
// 			<View className=" py-1">
// 				<Text className={`font-sans-bold text-lg ${darkTheme? "text-white":"text-black"}`}>
// 					5 stars :
// 				</Text>
// 			</View>
// 			<View className="flex-1 h-3 justify-end ">
// 				<PercentageBar
// 					percentage={48}
// 					width={width * 0.65}
// 				/>
// 			</View>
// 		</View>
// 	</View>
// )}

    // return (
    // 	<View
    // 		className={`bg-white gap-5 p-4 mx-3 rounded-3xl  ${
    // 			!FullMap
    // 				? "shadow-xl border border-gray-50 shadow-black/40"
    // 				: ""
    // 		}`}
    // 	>
    //     <View className="gap-3">
    //       {/* <------------------NAME-------------------> */}
    //       <View className="gap-3 flex-row items-end">
    //         {/* <Text className="font-sans-bold">Vendor Name: </Text> */}
    //         <View className="bg-gray-200 h-3 w-[100px] rounded-full" />
    //         <View className="bg-gray-200 h-3 w-[70px] rounded-full" />
    //       </View>
  
    //       {/* <-----------------RATING------------------> */}
    //       <View className="flex-row items-center gap-3">
    //         <View className="bg-gray-200 h-3 w-[70px] rounded-full" />
    //         <View className="bg-gray-200 h-3 w-[150px] rounded-full" />
  
    //         <View className="pl-3 flex-row gap-3 text-gray-500 items-end">
    //         </View>
    //       </View>
    //     </View>
  
    // 		{/* <------------FULL RATING STATS------------> */}
    // 		{!FullMap && (
    // 			<View className="gap-2">
    // 				{/* one star */}
    // 				<View
    // 					className="flex-row gap-4 items-center "
    // 					style={{
    // 						maxWidth: width * 0.8,
    // 					}}
    // 				>
    // 					<View className=" py-1">
    // 						<View className="bg-gray-200 h-3 w-[60px] rounded-full" />
    // 					</View>
    // 					<View className="flex-1 h-3 justify-end ">
    // 						<View className="bg-gray-200 h-3 w-[90%] rounded-full" />
    // 					</View>
    // 				</View>
  
    // 				{/* two star */}
    // 				<View
    // 					className="flex-row gap-4 items-center "
    // 					style={{
    // 						maxWidth: width * 0.8,
    // 					}}
    // 				>
    // 					<View className=" py-1">
    // 						<View className="bg-gray-200 h-3 w-[60px] rounded-full" />
    // 					</View>
    // 					<View className="flex-1 h-3 justify-end ">
    // 						<View className="bg-gray-200 h-3 w-[90%] rounded-full" />
    // 					</View>
    // 				</View>
  
    // 				{/* three star */}
    // 				<View
    // 					className="flex-row gap-4 items-center "
    // 					style={{
    // 						maxWidth: width * 0.8,
    // 					}}
    // 				>
    // 					<View className=" py-1">
    // 						<View className="bg-gray-200 h-3 w-[60px] rounded-full" />
    // 					</View>
    // 					<View className="flex-1 h-3 justify-end ">
    // 						<View className="bg-gray-200 h-3 w-[90%] rounded-full" />
    // 					</View>
    // 				</View>
  
    // 				{/* four star */}
    // 				<View
    // 					className="flex-row gap-4 items-center "
    // 					style={{
    // 						maxWidth: width * 0.8,
    // 					}}
    // 				>
    // 					<View className=" py-1">
    // 						<View className="bg-gray-200 h-3 w-[60px] rounded-full" />
    // 					</View>
    // 					<View className="flex-1 h-3 justify-end ">
    // 						<View className="bg-gray-200 h-3 w-[90%] rounded-full" />
    // 					</View>
    // 				</View>
  
    // 				{/* five star */}
    // 				<View
    // 					className="flex-row gap-4 items-center "
    // 					style={{
    // 						maxWidth: width * 0.8,
    // 					}}
    // 				>
    // 					<View className=" py-1">
    // 						<View className="bg-gray-200 h-3 w-[60px] rounded-full" />
    // 					</View>
    // 					<View className="flex-1 h-3 justify-end ">
    // 						<View className="bg-gray-200 h-3 w-[90%] rounded-full" />
    // 					</View>
    // 				</View>
    // 			</View>
    // 		)}
    // 		{/* <--------------EST DISTANCE---------------> */}
    // 		<View className=" flex-row gap-2 items-end">
    // 			{/* <Text className="font-sans-bold">Delivery Time:</Text> */}
    // 						<View className="bg-gray-200 h-3 w-[60px] rounded-full" />
    // 						<View className="bg-gray-200 h-3 w-[60px] rounded-full" />
  
    // 			{/* <Text>{`${"45min"}</Text> */}
    // 		</View>
  
    // 		{/* <--------------EST DELIVERY---------------> */}
  
    // 		{/* <-----------VIEW VENDOR BUTTON------------> */}
    // 		<PressableScale
    // 			activeOpacity={0.7}
    // 			onPress={() => {
    // 				router.push(`/(screens)/vendor/[id:1]`);
    // 			}}
    // 		>
    // 			{/* <Button
    // 				style={"w-[200px] self-end rounded"}
    // 				label={"View Vendor Shop"}
    // 				textStyle={""}
    // 			/> */}
    // 						<View className="bg-gray-200 h-[0px] w-[200px] self-end rounded" />
  
    // 		</PressableScale>
    // 	</View>
    // );