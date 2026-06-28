import Dashboard from "./components/Dashboard";

export default function Home() {
  return (
    <div className="min-h-[calc(100vh-4rem)] w-full bg-background px-4 py-6 sm:px-6 lg:px-8">
      <main className="w-full font-mono text-slate-900 dark:text-green-300">
        <Dashboard />
      </main>
    </div>
  );
}
