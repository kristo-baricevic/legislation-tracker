"use client";
import React from "react";

interface Bills {
  congress: number;
  latestAction: {
    actionDate: string;
    text: string;
  };
  number: string;
  originChamber: string;
  originChamberCode: string;
  title: string;
  type: string;
  updateDate: string;
  updateDateIncludingText: string;
  url: string;
}

interface BillData {
  bills: Bills[];
  pagination: {
    count: number;
    next: string;
  };
  request: {
    contentType: string;
    format: string;
  };
}

const useFetchBill = (): Bills[] => {
  const [bills, setBills] = React.useState<Bills[]>([]);
  const host = `https://api.congress.gov/v3/bill?format=json`;
  const apiKey = process.env.NEXT_PUBLIC_CONGRESS_API_KEY;
  const url = host + "&api_key=" + apiKey;

  React.useEffect(() => {
    const fetchData = async () => {
      const data = await fetch(url);
      const dataJason: BillData = await data.json();
      setBills(dataJason.bills);
    };

    fetchData();
  }, [url]);

  return bills;
};

export default function FetchBill() {
  const billData = useFetchBill();

  type DisplayColumns = "title" | "congress" | "originChamber";

  const columns: DisplayColumns[] = ["title", "congress", "originChamber"];

  //   console.log("bill data is ", billData);

  return (
    <div className="w-full bg-background">
      <main className="w-full px-4 py-6 font-mono text-slate-900 dark:text-green-300 sm:px-6 lg:px-10 2xl:px-12">
        <h1 className="mb-8">Bills</h1>
        <div className="rounded-lg border border-slate-400 dark:border-green-800">
          <table className="w-full text-left">
            <thead>
              <tr>
                {columns.map((h) => (
                  <th className="px-4 py-3" key={h}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>

            <tbody>
              {billData.map((bill) => (
                <tr key={bill.number}>
                  {columns.map((col) => (
                    <td className="px-4 py-4" key={col}>
                      {bill[col]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>
    </div>
  );
}
