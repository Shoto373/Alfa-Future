import type { ReactNode } from "react";
import Shell from "@/components/Shell";

export default function ManagerLayout({ children }: { children: ReactNode }) {
  return <Shell>{children}</Shell>;
}
