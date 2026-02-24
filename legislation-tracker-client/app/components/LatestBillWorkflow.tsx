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

      //vote data
      const detailsRes = await fetch(
        `${url2}/${congress}/${billType}/${billNumber}`
      );
      const detailsJson = await detailsRes.json();

      const votesRes = await fetch(
        `${url2}/${congress}/${billType}/${billNumber}/votes`
      );

      const votesJson = await votesRes.json();

      const vote = votesJson.votes?.[0];

      console.log("votes json", votesJson);

      if (!vote) return;

      const rollNumber = vote.rollNumber;
      const chamber = vote.chamber.toLowerCase();

      const voteRes = await fetch(
        `${url3}/${congress}/${chamber}/${rollNumber}`
      );

      const voteJson = await voteRes.json();
      // use reg ex to extract the text 'Roll' plus a digit

      //[
      //   "Roll no. 250", // index 0 → full matched text
      //   "250"           // index 1 → first capture group
      // ]

      console.log("vote json", voteJson);

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
