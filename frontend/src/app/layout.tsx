import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TruthGuard-Chronos",
  description: "Temporal-Provenance Conflict Graph with Deep Agent Verification",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-white text-slate-900 min-h-screen antialiased">
        {children}
      </body>
    </html>
  );
}
