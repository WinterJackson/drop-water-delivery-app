import { View, Image } from "react-native";
import { Text } from '@/components/ui/Text';
import React from "react";
import { useRouter } from "expo-router";
import { PressableScale } from "@/components/ui/PressableScale";

type Props = {
  style: string;
  textStyle?: string;
  label: string;
  type?: string; 
  iconright?: any;
  iconleft?: any;
  iconcolor?: string;
  onPress?: () => void;
};

const Button = ({ style, label, type, textStyle, iconleft, iconright, iconcolor, onPress }: Props) => {
  const router = useRouter();

  return (
    <PressableScale onPress={onPress}>
      <View
        className={`p-[10px] flex-row items-center justify-center shadow-xl gap-3 ${type==="outline" ? "border border-gray-400 " : "bg-accentbg"}  ${style}`}
      >
        {
          iconleft && (
            <View className=" w-7 h-7 ">
              <Image source={iconleft} className="w-full h-full" tintColor={iconcolor || "white"} />
            </View>
          )
        }
        <Text numberOfLines={1} className={` whitespace-nowrap ${type ==="outline" ? "" : textStyle !=null && textStyle != ""? "": "text-white"}  ${textStyle}`}> {label}</Text>
        {
          iconright && (
            <View className=" w-7 h-7 ">
              <Image source={iconright} className="w-full h-full" tintColor={iconcolor || "white"} />
            </View>
          )
        }
      </View>
    </PressableScale>
  );
};

export default Button;
