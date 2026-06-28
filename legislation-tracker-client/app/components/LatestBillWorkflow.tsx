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

interface RecentBill {
  congress: number;
  type: string;
  number: string;
}

interface RecentBillsResponse {
  bills?: RecentBill[];
}

interface RecordedVoteAction {
  recordedVotes?: Array<{ url: string }>;
}

interface ActionsResponse {
  actions?: RecordedVoteAction[];
}

interface BillActionsResponse {
  bill?: {
    title?: string;
    actions?: {
      url?: string;
    };
  };
}

type VoteMember = ReturnType<typeof parseHouseRollCallXml>[number];

interface LatestBillWorkflowData {
  bill: BillActionsResponse;
  vote: VoteMember[];
}

export default function LatestBillWorkflow() {
  const [data, setData] = React.useState<LatestBillWorkflowData | null>(null);

  React.useEffect(() => {
    const fetchLatestVotedBill = async () => {
      // 1. Get recently updated bills
      const billsRes = await fetch(`/api/congress/recent?congress=119&type=hr`);
      const billsJson = (await billsRes.json()) as RecentBillsResponse;

      for (const bill of billsJson.bills ?? []) {
        const { congress, type, number } = bill;

        // 2. Fetch actions for each bill
        const actionsRes = await fetch(
          `/api/congress/${congress}/${type.toLowerCase()}/${number}`
        );
        const actionsJson = (await actionsRes.json()) as BillActionsResponse;

        const actionsUrl = actionsJson?.bill?.actions?.url;
        if (!actionsUrl) continue;

        const actionsRes2 = await fetch(
          `/api/congress/action?url=${encodeURIComponent(actionsUrl)}`
        );
        const actionsData = (await actionsRes2.json()) as ActionsResponse;

        const voteAction = actionsData.actions?.find(
          (action) => action.recordedVotes && action.recordedVotes.length > 0
        );

        if (voteAction) {
          const voteUrl = voteAction.recordedVotes?.[0]?.url;
          if (!voteUrl) continue;

          const voteRes = await fetch(
            `/api/congress/action?url=${encodeURIComponent(voteUrl)}`
          );

          const contentType = voteRes.headers.get("content-type") || "";

          let voteData;

          if (contentType.includes("application/json")) {
            const jsonVoteData = await voteRes.json();
            voteData = Array.isArray(jsonVoteData) ? jsonVoteData : [];
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
    <div className="w-full px-4 py-6 font-mono text-slate-900 dark:text-green-300 sm:px-6 lg:px-10 2xl:px-12">
      {data ? (
        <>
          <h2 className="mb-4 text-xl font-semibold text-slate-900 dark:text-green-400">
            {data.bill.bill?.title}
          </h2>

          <div className="rounded-lg border border-slate-400 dark:border-green-800">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-slate-400 bg-slate-300/80 dark:border-green-800 dark:bg-green-950/20">
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">Party</th>
                  <th className="px-4 py-3">State</th>
                  <th className="px-4 py-3">Vote</th>
                </tr>
              </thead>
              <tbody>
                {data.vote.map((member, index) => (
                  <tr
                    key={index}
                    className="border-b border-slate-300 dark:border-green-900/50"
                  >
                    <td className="px-4 py-3">{member.name}</td>
                    <td className="px-4 py-3">{member.party}</td>
                    <td className="px-4 py-3">{member.state}</td>
                    <td className="px-4 py-3">{member.vote}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        "Loading..."
      )}
    </div>
  );
}
