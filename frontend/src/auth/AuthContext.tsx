import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, setOnAuthLost, tokens } from "@/api/client";
import type { Me } from "@/api/types";

declare global {
  interface Window {
    Telegram?: { WebApp?: { initData?: string; ready?: () => void; expand?: () => void } };
  }
}

interface AuthState {
  user: Me | null;
  loading: boolean;
  login: (phone: string, password: string) => Promise<void>;
  logout: () => void;
  can: (...perms: string[]) => boolean;
  canAny: (...perms: string[]) => boolean;
  refreshMe: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const queryClient = useQueryClient();

  const logout = useCallback(() => {
    const refresh = tokens.refresh;
    // Revoke server-side too; fire-and-forget, logout must work even offline.
    if (refresh) api.post("/auth/logout/", { refresh }).catch(() => {});
    tokens.clear();
    setUser(null);
    queryClient.clear();
  }, [queryClient]);

  const refreshMe = useCallback(async () => {
    const { data } = await api.get<Me>("/auth/me/");
    setUser(data);
  }, []);

  useEffect(() => {
    setOnAuthLost(() => setUser(null));
    (async () => {
      try {
        const tg = window.Telegram?.WebApp;
        tg?.ready?.();
        tg?.expand?.();
        if (tokens.access) {
          await refreshMe();
        } else if (tg?.initData) {
          // Opened from the bot: the initData signature is verified server-side.
          const { data } = await api.post("/auth/telegram/", { init_data: tg.initData });
          tokens.set(data.access, data.refresh);
          setUser(data.user);
        }
      } catch {
        tokens.clear();
      } finally {
        setLoading(false);
      }
    })();
  }, [refreshMe]);

  const login = useCallback(async (phone: string, password: string) => {
    const { data } = await api.post("/auth/login/", { phone, password });
    tokens.set(data.access, data.refresh);
    setUser(data.user);
  }, []);

  const value = useMemo<AuthState>(() => {
    const has = (p: string) => !!user && (user.is_superuser || user.permissions.includes(p));
    return {
      user,
      loading,
      login,
      logout,
      refreshMe,
      can: (...perms) => perms.every(has),
      canAny: (...perms) => perms.some(has),
    };
  }, [user, loading, login, logout, refreshMe]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
