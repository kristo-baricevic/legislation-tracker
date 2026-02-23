"use client";

import React from "react";
import FetchBill from "./FetchBill";
import FetchAmendments from "./FetchAmendments";
import FetchBillsGovInfo from "./FetchBillsGovInfo";
import LatestBillWorkflow from "./LatestBillWorkflow";

export default function Dashboard() {
  const [showBills, setShowBills] = React.useState<boolean>(false);
  const [showAmendments, setShowAmendments] = React.useState<boolean>(false);
  const [showGovInfoBills, setShowGovInfoBills] =
    React.useState<boolean>(false);
  const [latestBillWorkflow, setLatestBillWorkflow] =
    React.useState<boolean>(false);

  return (
    <>
      <div className="flex flex-row bg-slate-600 gap-x-12 p-2 mb-8">
        <button
          className="flex cursor-pointer hover:bg-slate-500 p-12"
          onClick={() => {
            setShowAmendments(false);
            setShowGovInfoBills(false);
            setShowBills(true);
            setLatestBillWorkflow(false);
          }}
        >
          BILLS
        </button>
        <button
          className="flex cursor-pointer hover:bg-slate-500 p-12"
          onClick={() => {
            setShowBills(false);
            setShowGovInfoBills(false);
            setShowAmendments(true);
            setLatestBillWorkflow(false);
          }}
        >
          AMENDMENTS
        </button>
        <button
          className="flex cursor-pointer hover:bg-slate-500 p-12"
          onClick={() => {
            setShowBills(false);
            setShowAmendments(false);
            setShowGovInfoBills(true);
            setLatestBillWorkflow(false);
          }}
        >
          GOVINFO BILLS
        </button>
        <button
          className="flex cursor-pointer hover:bg-slate-500 p-12"
          onClick={() => {
            setShowBills(false);
            setShowAmendments(false);
            setShowGovInfoBills(false);
            setLatestBillWorkflow(true);
          }}
        >
          LATEST BILL WORKFLOW
        </button>
        <button
          className="flex cursor-pointer hover:bg-slate-500 p-12"
          onClick={() => {
            setShowBills(false);
            setShowAmendments(false);
            setShowGovInfoBills(false);
            setLatestBillWorkflow(false);
          }}
        >
          CLOSE
        </button>
      </div>
      {showBills ? <FetchBill /> : ""}
      {showAmendments ? <FetchAmendments /> : ""}
      {showGovInfoBills ? <FetchBillsGovInfo /> : ""}
      {latestBillWorkflow ? <LatestBillWorkflow /> : ""}
    </>
  );
}
