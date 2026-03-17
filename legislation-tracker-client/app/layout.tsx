import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import AuthNav from "./components/AuthNav";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Legislation Tracker",
  description: "Track federal legislation and get plain-language summaries",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <header className="flex items-center justify-between border-b border-green-900/50 bg-black px-4 py-3">
          <a href="/" className="font-mono text-lg font-medium text-green-400">
            Legislation Tracker
          </a>
          <AuthNav />
        </header>
        {children}
      </body>
    </html>
  );
}
