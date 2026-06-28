"use client";
import React from "react";

interface Amendments {
  congress: number;
  description: string;
  latestAction: {
    actionDate: string;
    actionTime?: string;
    text: string;
  };
  number: string;
  purpose: string;
  type: string;
  updateDate: string;
  url: string;
}

interface AmendmentData {
  amendments: Amendments[];
  // pagination: {
  //   count: number;
  //   next: string;
  // };
  // request: {
  //   contentType: string;
  //   format: string;
  // };
}

const useFetchAmendments = (): Amendments[] => {
  const [amendments, setAmendments] = React.useState<Amendments[]>([]);
  const host = `https://api.congress.gov/v3/amendment?format=json`;
  const apiKey = process.env.NEXT_PUBLIC_CONGRESS_API_KEY;
  const url = host + "&api_key=" + apiKey;

  React.useEffect(() => {
    const fetchData = async () => {
      const data = await fetch(url);
      const dataJson: AmendmentData = await data.json();
      console.log("data json amend", dataJson);
      setAmendments(dataJson.amendments);
    };

    fetchData();
  }, [url]);

  return amendments;
};

export default function FetchAmendments() {
  const amendmentData = useFetchAmendments();

  type DisplayColumns = "description" | "purpose";

  const columns: DisplayColumns[] = ["description", "purpose"];

  // console.log("amendment data is ", amendmentData);

  return (
    <div className="w-full bg-background">
      <main className="w-full px-4 py-6 font-mono text-slate-900 dark:text-green-300 sm:px-6 lg:px-10 2xl:px-12">
        <h1 className="mb-8">Amendments</h1>
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
              {amendmentData.map((a, idx) => (
                <tr key={idx}>
                  {columns.map((col) => (
                    <td className="px-4 py-4" key={col}>
                      {a[col]}
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
