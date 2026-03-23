import AuthNav from "./AuthNav";
import ThemeToggle from "./ThemeToggle";

export default function SiteHeader() {
  return (
    <header className="flex items-center justify-between border-b border-slate-400/60 bg-slate-300 px-4 py-3 dark:border-green-900/50 dark:bg-black">
      <a
        href="/"
        className="cursor-pointer font-mono text-lg font-medium text-slate-900 dark:text-green-400"
      >
        Legislation Tracker
      </a>
      <div className="flex items-center gap-4">
        <ThemeToggle />
        <AuthNav />
      </div>
    </header>
  );
}
