import DashboardLoading from "./components/DashboardLoading";
import BillDeck from "./components/BillDeck";
import styles from "./components/bill-deck.module.css";

export default function Home() {
  return (
    <div className="min-h-[calc(100vh-4rem)] w-full bg-background px-4 py-6 sm:px-6 lg:px-8">
      <main className="w-full font-sans text-slate-900 dark:text-green-300">
        <div className={styles.pageFrame}>
          <div className={styles.page}>
            <DashboardLoading><BillDeck /></DashboardLoading>
          </div>
        </div>
      </main>
    </div>
  );
}
