"use client";

import React from "react";

interface Package {
  packageId: string;
  lastModified: string;
  packageLink: string;
  docClass: string;
  title: string;
  congress: string;
  dateIssued: string;
}

interface GovInfoBills {
  count: number;
  message: string | null;
  nextPage: string | null;
  previousPage: string | null;
  packages: Package[];
}

export default function FetchBillsGovInfo() {
  const [bills, setBills] = React.useState<Package[]>([]);

  const url = "/api/govinfo";

  React.useEffect(() => {
    const fetchData = async () => {
      const data = await fetch(url);
      const dataJson = (await data.json()) as GovInfoBills;
      setBills(dataJson.packages ?? []);
    };
    fetchData();
  }, [url]);

  console.log("data is ", bills);

  return (
    <div className="w-full px-4 py-6 font-mono text-slate-900 dark:text-green-300 sm:px-6 lg:px-10 2xl:px-12">
      <h1 className="mb-4">Fetch Bills</h1>
      {bills.map((b) => (
        <div className="mb-4 overflow-hidden rounded border border-slate-400 bg-white/70 p-4 dark:border-green-900/70 dark:bg-black" key={b.packageId}>
          <div>{b.title}</div>
          <div>{b.dateIssued}</div>
        </div>
      ))}
    </div>
  );
}
