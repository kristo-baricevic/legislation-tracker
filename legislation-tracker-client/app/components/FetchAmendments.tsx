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
      let data = await fetch(url);
      let dataJson: AmendmentData = await data.json();
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
    <div className="flex min-h-screen items-center justify-center bg-black">
      <main className="flex min-h-screen w-full max-w-3xl flex-col items-center justify-between py-32 px-16 text-green-300 font-mono sm:items-start ">
        <h1 className="mb-8">Amendments</h1>
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
            {amendmentData.map((a, idx) => (
              <tr key={idx}>
                {columns.map((col) => (
                  <td className="py-8 px-4" key={col}>
                    {a[col]}
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
