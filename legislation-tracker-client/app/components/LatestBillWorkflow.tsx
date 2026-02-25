"use client";
import React from "react";

export default function LatestBillWorkflow() {
  const [congressData, setCongressData] = React.useState<any>(null);
  const url = "/api/latest";
  const url2 = "/api/congress";
  const url3 = "/api/congress/vote";
  React.useEffect(() => {
    const fetchData = async () => {
      //get most recent bill
      const billRes = await fetch(url);
      const billJson: any = await billRes.json();
      console.log("data returned ", billJson);

      const { congress, billType, billNumber } = billJson;

      if (!congress || !billType || !billNumber) {
        console.log(
          "no destructured data",
          billJson.congress,
          billJson.billType,
          parseInt(billJson.billNumber)
        );
        return;
      }

      console.log(
        " congress ",
        congress,
        " bill type ",
        billType,
        " bill number ",
        billNumber
      );

      // 1) get actions
      const actionsRes = await fetch(
        `${url2}/${congress}/${billType}/${billNumber}`
      );
      const actionsJson = await actionsRes.json();

      const actionsUrl = actionsJson?.bill?.actions?.url;

      if (!actionsUrl) {
        console.log("No actions URL found", actionsJson);
        return;
      }

      const actionsRes2 = await fetch(
        `/api/congress/action?url=${encodeURIComponent(actionsUrl)}`
      );
      const actionsData = await actionsRes2.json();
      console.log("actionsJson", actionsJson);
      // 2) find roll call text
      const voteAction = actionsData.actions.find((a: any) =>
        a.text.includes("Roll no.")
      );

      if (!voteAction) return;

      const rollMatch = voteAction.text.match(/Roll no\. (\d+)/i);
      const rollNumber = rollMatch?.[1];

      const chamber = voteAction.text.includes("Senate") ? "senate" : "house";

      const voteUrl = voteAction?.recordedVotes?.[0]?.url;

      if (!voteUrl) {
        console.log("No recordedVotes URL found", voteAction);
        return;
      }

      const voteRes = await fetch(
        `/api/congress/action?url=${encodeURIComponent(voteUrl)}`
      );
      const voteJson = await voteRes.json();

      console.log("bill data ", billJson, "vote data", voteJson);
      setCongressData({
        bill: billJson,
        vote: voteJson,
      });
    };

    fetchData();
  }, [url]);

  return (
    <div>
      <h1>Latest Bill Workflow</h1>

      <div>
        {/* JSON.stringify(object, null, 2)
        null = no filtering
        2 = pretty print with 2-space indentation */}
        {congressData
          ? JSON.stringify(congressData, null, 2)
          : "no congress data fetched"}
      </div>
    </div>
  );
}
