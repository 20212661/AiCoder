import React, { createContext, useContext, useState, useCallback, type ReactNode } from 'react';
import { getTheme, type ThemeName } from '../utils/theme.js';

type ThemeContextValue = [ThemeName, (theme: ThemeName | 'auto') => void];

const ThemeContext = createContext<ThemeContextValue>(['dark', () => {}]);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [themeName, setThemeNameRaw] = useState<ThemeName>('dark');

  const setThemeName = useCallback((theme: ThemeName | 'auto') => {
    if (theme === 'auto') {
      setThemeNameRaw('dark');
    } else {
      setThemeNameRaw(theme);
    }
  }, []);

  return React.createElement(
    ThemeContext.Provider,
    { value: [themeName, setThemeName] },
    children,
  );
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}

export function useThemeSetting(): [ThemeName | 'auto', (theme: ThemeName | 'auto') => void] {
  return useContext(ThemeContext);
}

export function usePreviewTheme() {
  return {
    setPreviewTheme: (_theme: ThemeName | undefined) => {},
    savePreview: () => {},
    cancelPreview: () => {},
  };
}
