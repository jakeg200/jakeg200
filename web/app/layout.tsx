import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "warrant",
  description:
    "Assessment of derivations rather than answers. A claim is only as good as the warrant behind it.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <div className="mx-auto max-w-3xl px-5 py-10">
          <header className="mb-10 flex items-baseline justify-between border-b border-[var(--color-line)] pb-4">
            <Link href="/" className="text-lg font-semibold tracking-tight">
              warrant
            </Link>
            <span className="text-xs text-[var(--color-muted)]">
              a claim is only as good as the warrant behind it
            </span>
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}
