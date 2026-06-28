import Link from "next/link";
import AuthNav from "./AuthNav";
import ThemeToggle from "./ThemeToggle";

export default function SiteHeader() {
  return (
    <header className="w-full border-b border-slate-400/60 bg-slate-300 dark:border-green-900/50 dark:bg-black">
      <div className="flex w-full flex-row flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6 lg:px-8">
        <Link
          href="/"
          className="cursor-pointer font-mono text-lg font-medium text-slate-900 dark:text-green-400"
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
