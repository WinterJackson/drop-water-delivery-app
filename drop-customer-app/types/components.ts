import { KeyboardTypeOptions } from 'react-native';

export interface InputFieldProps {
  label: string;
  value: string;
  onChangeText: (text: string) => void;
  keyboardType?: KeyboardTypeOptions;
  editable?: boolean;
  maxLength?: number;
}

export interface ActionItemProps {
  title: string;
  icon: string;
  description?: string;
  onPress: () => void;
}

export interface ToggleItemProps {
  title: string;
  icon: string;
  description?: string;
  value: boolean;
  onToggle: (value: boolean) => void;
}
