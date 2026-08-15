import { create } from 'zustand';

export type ToastType = 'success' | 'error' | 'info';

/** Safely coerce any value into a renderable string */
const safeString = (val: unknown): string => {
  if (val === null || val === undefined) return '';
  if (typeof val === 'string') return val;
  if (typeof val === 'number' || typeof val === 'boolean') return String(val);
  if (Array.isArray(val)) {
    // Handle FastAPI validation error arrays: [{type, loc, msg, input}, ...]
    return val.map((item) => {
      if (typeof item === 'object' && item !== null && 'msg' in item) return String(item.msg);
      return String(item);
    }).join('; ');
  }
  if (typeof val === 'object') {
    const obj = val as Record<string, unknown>;
    if ('msg' in obj) return String(obj.msg);
    if ('message' in obj) return String(obj.message);
    if ('detail' in obj) {
      // FastAPI detail can be string or array
      if (typeof obj.detail === 'string') return obj.detail;
      if (Array.isArray(obj.detail)) return obj.detail.map((d) => (d as { msg?: string })?.msg || String(d)).join('; ');
      return String(obj.detail);
    }
    try { return JSON.stringify(val); } catch { return '[Object]'; }
  }
  return String(val);
};

interface ToastState {
  visible: boolean;
  type: ToastType;
  title: string;
  message?: string;
  timeoutId?: NodeJS.Timeout | number | null;
}

interface ToastActions {
  showToast: (type: ToastType, title: unknown, message?: unknown, duration?: number) => void;
  hideToast: () => void;
}

const initialState: ToastState = {
  visible: false,
  type: 'info',
  title: '',
  message: undefined,
  timeoutId: null,
};

export const useToastStore = create<ToastState & ToastActions>((set, get) => ({
  ...initialState,

  showToast: (type, title, message, duration = 4000) => {
    // Clear any existing timeout so it doesn't close prematurely
    const existingTimeout = get().timeoutId;
    if (existingTimeout) {
      clearTimeout(existingTimeout);
    }

    const newTimeout = setTimeout(() => {
      set({ visible: false });
    }, duration);

    set({
      visible: true,
      type,
      title: safeString(title),
      message: message !== undefined && message !== null ? safeString(message) : undefined,
      timeoutId: newTimeout,
    });
  },

  hideToast: () => {
    const existingTimeout = get().timeoutId;
    if (existingTimeout) {
      clearTimeout(existingTimeout);
    }
    set({ visible: false, timeoutId: null });
  },
}));
