import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";

import {
  ApiError,
  getMe,
  login as apiLogin,
  logout as apiLogout,
  restoreCsrfTokenFromCookie,
  setCsrfToken,
} from "@/services/api";
import type { ApiUser } from "@/types/api";

type AuthState = {
  user: ApiUser | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<ApiUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    restoreCsrfTokenFromCookie();
    getMe()
      .then((current) => {
        if (mounted) setUser(current);
      })
      .catch(() => {
        setCsrfToken(null);
        if (mounted) setUser(null);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      login: async (username, password) => {
        try {
          const authenticated = await apiLogin(username, password);
          setUser(authenticated);
          toast.success("Login realizado.");
        } catch (error) {
          const message =
            error instanceof ApiError && error.status === 401
              ? "Usuário ou senha inválidos."
              : error instanceof ApiError
                ? error.message
                : "Não foi possível entrar.";
          toast.error(message);
          throw error;
        }
      },
      logout: async () => {
        try {
          await apiLogout();
        } finally {
          setUser(null);
          setCsrfToken(null);
          toast.message("Sessão encerrada.");
        }
      },
    }),
    [loading, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
