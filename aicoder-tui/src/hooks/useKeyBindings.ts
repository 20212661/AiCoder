import { useInput } from "ink";

export interface KeyHandlers {
  submit?: () => void;
  cancel?: () => void;
  scrollUp?: () => void;
  scrollDown?: () => void;
  toggleSidebar?: () => void;
  switchModel?: () => void;
  clearChat?: () => void;
  quit?: () => void;
}

export function useKeyBindings(handlers: KeyHandlers) {
  useInput((input, key) => {
    if (key.return) handlers.submit?.();
    else if (key.escape) handlers.cancel?.();
    else if (key.ctrl && input === "p") handlers.scrollUp?.();
    else if (key.ctrl && input === "n") handlers.scrollDown?.();
    else if (key.ctrl && input === "b") handlers.toggleSidebar?.();
    else if (key.ctrl && input === "m") handlers.switchModel?.();
    else if (key.ctrl && input === "l") handlers.clearChat?.();
    else if (key.ctrl && input === "c") handlers.quit?.();
  });
}
