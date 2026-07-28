import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Atrium",
  description: "A room you enter and stay in until a concept clicks.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      {/* Extensions (Grammarly and friends) inject attributes onto <body> before React
          hydrates, which reads as a mismatch. Suppressing it here is the standard fix and
          only covers this element's own attributes. */}
      <body className="antialiased" suppressHydrationWarning>
        {children}
      </body>
    </html>
  );
}
