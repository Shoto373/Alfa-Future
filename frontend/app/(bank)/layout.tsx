import type { ReactNode } from "react";
import Shell from "@/components/Shell";

export default function BankLayout({ children }: { children: ReactNode }) {
  return <Shell>{children}</Shell>;
}
