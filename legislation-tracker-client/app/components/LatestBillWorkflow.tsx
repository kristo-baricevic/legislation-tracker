"use client";
import React from "react";

function parseHouseRollCallXml(xmlString: string) {
  const parser = new DOMParser();
  const xml = parser.parseFromString(xmlString, "text/xml");

  const votes = Array.from(xml.getElementsByTagName("recorded-vote"));

  return votes.map((node) => {
    const legislator = node.getElementsByTagName("legislator")[0];
    const vote = node.getElementsByTagName("vote")[0];

    return {
      name: legislator?.textContent?.trim(),
      party: legislator?.getAttribute("party"),
      state: legislator?.getAttribute("state"),
      vote: vote?.textContent?.trim(),
    };
  });
}

export default function LatestBillWorkflow() {
  const [data, setData] = React.useState<any>(null);

  React.useEffect(() => {
    const fetchLatestVotedBill = async () => {
      const apiKey = process.env.NEXT_PUBLIC_CONGRESS_API_KEY;

      // 1. Get recently updated bills
      const billsRes = await fetch(`/api/congress/recent?congress=119&type=hr`);
      const billsJson = await billsRes.json();

      for (const bill of billsJson.bills) {
        const { congress, type, number } = bill;

        // 2. Fetch actions for each bill
        const actionsRes = await fetch(
          `/api/congress/${congress}/${type.toLowerCase()}/${number}`
        );
        const actionsJson = await actionsRes.json();

        const actionsUrl = actionsJson?.bill?.actions?.url;
        if (!actionsUrl) continue;

        const actionsRes2 = await fetch(
          `/api/congress/action?url=${encodeURIComponent(actionsUrl)}`
        );
        const actionsData = await actionsRes2.json();

        const voteAction = actionsData.actions.find(
          (a: any) => a.recordedVotes && a.recordedVotes.length > 0
        );

        if (voteAction) {
          const voteUrl = voteAction.recordedVotes[0].url;

          const voteRes = await fetch(
            `/api/congress/action?url=${encodeURIComponent(voteUrl)}`
          );

          const contentType = voteRes.headers.get("content-type") || "";

          let voteData;

          if (contentType.includes("application/json")) {
            voteData = await voteRes.json();
          } else {
            const xmlText = await voteRes.text();
            voteData = parseHouseRollCallXml(xmlText);
          }

          setData({
            bill: actionsJson,
            vote: voteData,
          });

          return; // stop at first voted bill
        }
      }
    };

    fetchLatestVotedBill();
  }, []);

  return (
    <div>
      {data ? (
        <>
          <h2>{data.bill.bill.title}</h2>

          <table border={1} cellPadding={6}>
            <thead>
              <tr>
                <th>Name</th>
                <th>Party</th>
                <th>State</th>
                <th>Vote</th>
              </tr>
            </thead>
            <tbody>
              {data.vote.map((member: any, index: number) => (
                <tr key={index}>
                  <td>{member.name}</td>
                  <td>{member.party}</td>
                  <td>{member.state}</td>
                  <td>{member.vote}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : (
        "Loading..."
      )}
    </div>
  );
}
