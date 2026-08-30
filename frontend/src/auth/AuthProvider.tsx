import { useQueryClient, useQuery, useMutation } from "@tanstack/react-query";
import { createContext, useContext, type ReactNode } from "react";

import { api, ApiError, type CurrentUser } from "../lib/api";

interface AuthContextValue {
  user: CurrentUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<CurrentUser>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const userQuery = useQuery({
    queryKey: ["current-user"],
    queryFn: () => api<CurrentUser>("/auth/me"),
    retry: (count, error) => !(error instanceof ApiError && error.status === 401) && count < 2,
    staleTime: 60_000,
  });
  const loginMutation = useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      api<CurrentUser>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      }),
    onSuccess: (user) => queryClient.setQueryData(["current-user"], user),
  });
  const logoutMutation = useMutation({
    mutationFn: () => api<void>("/auth/logout", { method: "POST" }),
    onSuccess: () => {
      queryClient.setQueryData(["current-user"], null);
      queryClient.removeQueries({ predicate: ({ queryKey }) => queryKey[0] !== "current-user" });
    },
  });

  return (
    <AuthContext.Provider
      value={{
        user: userQuery.data ?? null,
        loading: userQuery.isPending,
        login: (email, password) => loginMutation.mutateAsync({ email, password }),
        logout: () => logoutMutation.mutateAsync(),
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
