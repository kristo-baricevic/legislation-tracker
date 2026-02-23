"use client";
import React from "react";

export default function LatestBillWorkflow() {
  const [congressData, setCongressData] = React.useState<any>(null);
  const url = "/api/congress/bill/latest";
  const url2 = "/api/congress";
  const url3 = "/api/congress/vote";
  React.useEffect(() => {
    const fetchData = async () => {
      //get most recent bill
      const billRes = await fetch(url);
      const billJson: any = await billRes.json();
      console.log("data returned ", billJson.bills);

      const { congress, type: billType, number: billNumber } = billJson.bills;

      console.log(
        " congress ",
        congress,
        " bill type ",
        billType,
        " bill number ",
        billNumber
      );

      //vote data
      const detailsRes = await fetch(
        `${url2}/${congress}/${billType}/${billNumber}`
      );
      const detailsJson = await detailsRes.json();
      const actionsUrl = detailsJson.bill?.actions?.url;

      console.log(
        "data latest json",
        detailsJson,
        "actions",
        detailsJson.bill?.actions
      );

      const actionsRes = await fetch(
        `${actionsUrl}&api_key=${process.env.NEXT_PUBLIC_CONGRESS_API_KEY}`
      );
      const actionsJson = await actionsRes.json();
      const voteAction = actionsJson.actions.find((a: any) =>
        a.text.includes("Roll")
      );
      if (!voteAction) return;

      // use reg ex to extract the text 'Roll' plus a digit
      const rollMatch = voteAction.text.match(/Roll no\. (\d+)/i);

      //[
      //   "Roll no. 250", // index 0 → full matched text
      //   "250"           // index 1 → first capture group
      // ]
      const rollNumber = rollMatch?.[1];

      const chamber = voteAction.text.includes("Senate") ? "senate" : "house";

      const voteRes = await fetch(
        `${url3}/${congress}/${chamber}/${rollNumber}`
      );

      const voteJson = await voteRes.json();
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
