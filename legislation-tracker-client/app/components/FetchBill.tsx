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
      let data = await fetch(url);
      let dataJason: BillData = await data.json();
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
    <div className="flex min-h-screen items-center justify-center bg-black">
      <main className="flex min-h-screen w-full max-w-3xl flex-col items-center justify-between py-32 px-16 text-green-300 font-mono sm:items-start ">
        <h1 className="mb-8">Bills</h1>
        <table className="min-w-125">
          <thead>
            <tr>
              {columns.map((h) => (
                <th className="px-4" key={h}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>

          <tbody>
            {billData.map((bill) => (
              <tr key={bill.number}>
                {columns.map((col) => (
                  <td className="py-8 px-4" key={col}>
                    {bill[col]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </main>
    </div>
  );
}
