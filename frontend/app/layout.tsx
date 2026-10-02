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
      <body className="min-h-full flex flex-col">
        <header className="flex items-center justify-between border-b border-zinc-200 px-4 py-2">
          <h1 className="text-lg font-semibold">AirPower</h1>
          <Nav />
          <SyntheticBadge />
        </header>
        {children}
      </body>
    </html>
  );
}
