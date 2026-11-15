import React, { useState } from 'react'
import {
  Pressable,
  StyleSheet,
  type PressableProps,
  type StyleProp,
  type ViewStyle,
} from 'react-native'

interface TvFocusableProps extends Omit<PressableProps, 'style' | 'children'> {
  style?: StyleProp<ViewStyle>
  focusedStyle?: StyleProp<ViewStyle>
  focusScale?: number
  borderRadius?: number
  children: React.ReactNode | ((focused: boolean) => React.ReactNode)
}

/**
 * D-pad focusable wrapper for 10-foot TV UI.
 * Displays a high-contrast focus ring and subtle scale-up when focused.
 */
export function TvFocusable({
  style,
  focusedStyle,
  focusScale = 1.04,
  borderRadius = 12,
  children,
  onFocus,
  onBlur,
  ...rest
}: TvFocusableProps) {
  const [focused, setFocused] = useState(false)

  return (
    <Pressable
      {...rest}
      focusable
      onFocus={(e) => {
        setFocused(true)
        onFocus?.(e)
      }}
      onBlur={(e) => {
        setFocused(false)
        onBlur?.(e)
      }}
      style={[
        style,
        { borderRadius },
        focused && [
          styles.focusedBase,
          { transform: [{ scale: focusScale }], borderRadius },
          focusedStyle,
        ],
      ]}
    >
      {typeof children === 'function' ? children(focused) : children}
    </Pressable>
  )
}

const styles = StyleSheet.create({
  focusedBase: {
    borderColor: '#818cf8',
    borderWidth: 3,
    shadowColor: '#818cf8',
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.55,
    shadowRadius: 12,
    elevation: 10,
  },
})
