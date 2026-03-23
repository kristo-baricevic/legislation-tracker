import Dashboard from "./components/Dashboard";
import RequireAuth from "./components/RequireAuth";

export default function Home() {
  return (
    <RequireAuth>
      <div className="flex min-h-screen min-w-screen items-center justify-center bg-background">
        <main className="flex min-h-screen min-w-screen flex-col items-center justify-between py-32 px-8 font-mono text-slate-900 dark:text-green-300 sm:items-start ">
          <Dashboard />
        </main>
      </div>
    </RequireAuth>
  );
}
