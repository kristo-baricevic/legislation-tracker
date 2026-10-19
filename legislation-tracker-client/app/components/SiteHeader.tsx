import Link from "next/link";
import AuthNav from "./AuthNav";
import ThemeToggle from "./ThemeToggle";

export default function SiteHeader() {
  return (
    <header className="w-full border-b border-line bg-background">
      <div className="flex w-full flex-row flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6 lg:px-8">
        <Link
          href="/"
          className="cursor-pointer font-sans text-lg font-medium text-ink"
        >
          Legislation Tracker
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <ThemeToggle />
          <AuthNav />
        </div>
      </div>
    </header>
  );
}
