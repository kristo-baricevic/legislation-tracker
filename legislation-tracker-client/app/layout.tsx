import type { ReactNode } from "react";
import type { Metadata } from "next";
import { Geist, Geist_Mono, Atkinson_Hyperlegible_Next, Literata } from "next/font/google";
import SiteHeader from "./components/SiteHeader";
import ProfileExperience from "./components/ProfileExperience";
import { THEME_STORAGE_KEY } from "../lib/theme";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Card dashboard typefaces. Atkinson Hyperlegible was designed for low-vision
// readers; Literata is a screen-reading serif for long bill titles and summaries.
const uiSans = Atkinson_Hyperlegible_Next({
  variable: "--font-ui",
  subsets: ["latin"],
  adjustFontFallback: false,
  fallback: ["Arial", "sans-serif"],
});

const readingSerif = Literata({
  variable: "--font-reading",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Legislation Tracker",
  description: "Track federal legislation and get plain-language summaries",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  const themeInitScript = `(function(){try{var k=${JSON.stringify(THEME_STORAGE_KEY)};var t=localStorage.getItem(k);if(t==='dark')document.documentElement.classList.add('dark');else document.documentElement.classList.remove('dark');}catch(e){}})();`;

  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body
        className={`${geistSans.variable} ${geistMono.variable} ${uiSans.variable} ${readingSerif.variable} min-h-screen bg-background text-foreground antialiased`}
      >
        <ProfileExperience><SiteHeader />{children}</ProfileExperience>
      </body>
    </html>
  );
}
