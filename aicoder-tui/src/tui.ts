// Unified TUI exports - main API surface for the application
export { default as Box } from './design-system/ThemedBox.js';
export { default as Text } from './design-system/ThemedText.js';
export { ThemeProvider, useTheme, useThemeSetting, usePreviewTheme } from './design-system/ThemeProvider.js';
export { color } from './design-system/color.js';

export { default as BaseBox } from './ink/components/Box.js';
export { default as BaseText } from './ink/components/Text.js';
export { default as useInput } from './ink/hooks/use-input.js';
export { default as useApp } from './ink/hooks/use-app.js';
export { default as useStdin } from './ink/hooks/use-stdin.js';
export { useTerminalViewport } from './ink/hooks/use-terminal-viewport.js';
export { default as Newline } from './ink/components/Newline.js';
export { default as Spacer } from './ink/components/Spacer.js';
export { renderSync } from './ink/root.js';
export { default as measureElement } from './ink/measure-element.js';
