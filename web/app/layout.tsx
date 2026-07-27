import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Atrium",
  description: "A room you enter and stay in until a concept clicks.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
