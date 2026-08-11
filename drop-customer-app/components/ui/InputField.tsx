import {
    Image,
    StyleSheet,
    View,
    TextInputProps,
} from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import React, { useContext } from "react";
import { UIThemeContext } from "@/context/ThemeContext";
import { PressableScale } from "@/components/ui/PressableScale";
import { BRAND } from "@/constants/brandColors";
import { Ionicons } from "@expo/vector-icons";

type Props = TextInputProps & {
  label: string;
  type: string;
  style?: string;
  placeholder: string;
  set: (text: string) => void;
  iconleft?: string
};

const InputField = ({ label, style, type, placeholder, set, iconleft, ...rest }: Props) => {
  // <---------------HOOKS---------------->
  const {currentTheme} = useContext(UIThemeContext)
  const darkTheme = currentTheme === "dark";

  //   STATES
  const [showPassword, setShowPassword] = React.useState(false);

  return (
    <View
      className={`relative max-w-[350px] w-[90%] border ${darkTheme?"border-gray-100/20 bg-gray-200/20":"border-gray-500 bg-gray-100"} rounded-full h-[50px] px-5 flex-row items-center` + style
      }
    >
      {/* <View className={`px-2 py-[2px] ${darkTheme?"":"bg-gray-100"} absolute -top-3 left-5 rounded-full`}>
        <Text className={`${darkTheme?"text-white":""}`}>{label}</Text>
      </View> */}
      {iconleft != undefined && (
        <View className="h-full items-center justify-center">
          <View className="w-9 h-9 items-center justify-center  ">
              <Ionicons name={iconleft as any} size={24} color={BRAND.primary} />
          </View>
        </View>
        )}
      <TextInput
        placeholder={placeholder}
        placeholderTextColor={darkTheme ? BRAND.searchPlaceholderDark : BRAND.gray500}
        onChangeText={(text) => set(text)}
        secureTextEntry={type === "password" && !showPassword}
        className={`flex-1 ${darkTheme ? "text-white" : "text-black"}`}
        {...rest}
      />
      {type === "password" && (
        <PressableScale accessibilityLabel={showPassword ? "Hide password" : "Show password"} 
          className="justify-center items-center"
          activeOpacity={0.7}
          onPress={() => {
            setShowPassword(!showPassword)
          }}
        >
          <View className="w-9 h-9 items-center justify-center  ">
            {showPassword ? (
              <Ionicons name="eye-off" size={24} color={BRAND.primary} />
            ):(
              <Ionicons name="eye" size={24} color={BRAND.primary} />
            )}
          </View>
        </PressableScale>
      )}
    </View>
  );
};

export default InputField;

