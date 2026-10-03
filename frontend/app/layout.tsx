import type { Metadata } from "next";
import Nav from "@/components/Nav";
import SyntheticBadge from "@/components/SyntheticBadge";
import "./globals.css";

export const metadata: Metadata = {
  title: "AirPower — decision-support prototype",
  description:
    "Advisory air-operations planning prototype. All data is synthetic.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col bg-slate-50 text-slate-900">
        <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5">
            <div className="flex items-baseline gap-2">
              <span className="text-lg font-semibold tracking-tight">AirPower</span>
              <span className="hidden text-xs text-slate-500 sm:inline">Advisory planning prototype</span>
            </div>
            <Nav />
            <div className="ml-auto">
              <SyntheticBadge />
            </div>
          </div>
        </header>
        <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-5 px-4 py-6">{children}</main>
        <footer className="border-t border-slate-200 bg-white py-3 text-center text-xs text-slate-500">
          Advisory only: the system proposes, a human approves. Every figure shown comes from the API for this run.
        </footer>
      </body>
    </html>
  );
}
