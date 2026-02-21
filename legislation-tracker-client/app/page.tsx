import Dashboard from "./components/Dashboard";

export default function Home() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-black">
      <main className="flex min-h-screen w-full flex-col items-center justify-between py-32 px-8 text-green-300 font-mono sm:items-start ">
        <Dashboard />
      </main>
    </div>
  );
}
