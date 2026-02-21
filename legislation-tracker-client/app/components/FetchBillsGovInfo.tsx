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
      const dataJson: any = await data.json();
      setBills(dataJson.packages);
    };
    fetchData();
  }, [url]);

  console.log("data is ", bills);

  return (
    <div>
      <h1 className="mb-4">Fetch Bills</h1>
      {bills.map((b) => (
        <div className="mb-4" key={b.packageId}>
          <div>{b.title}</div>
          <div>{b.dateIssued}</div>
        </div>
      ))}
    </div>
  );
}
