import Dashboard from "./components/Dashboard";

export default function Home() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-black">
      <main className="flex min-h-screen w-full max-w-3xl flex-col items-center justify-between py-32 px-16 text-green-300 font-mono sm:items-start ">
        <Dashboard />
      </main>
    </div>
  );
}
