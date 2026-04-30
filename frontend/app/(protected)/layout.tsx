import type { ReactNode } from "react";

import { AppSidebar } from "../../components/AppSidebar";
import { AuthGuard } from "../../components/AuthGuard";
import { ThemeSync } from "../../components/ThemeSync";

export default function ProtectedLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard>
      <ThemeSync />
      <div className="flex h-screen bg-background text-foreground">
        <AppSidebar />
        <div className="flex-1 overflow-hidden">{children}</div>
      </div>
    </AuthGuard>
  );
}
