"use client";

import React from "react";
import FetchBill from "./FetchBill";
import FetchAmendments from "./FetchAmendments";

export default function Dashboard() {
  const [showBills, setShowBills] = React.useState<boolean>(false);
  const [showAmendments, setShowAmendments] = React.useState<boolean>(false);
  return (
    <>
      <div className="flex flex-row gap-x-12">
        <button
          className="flex"
          onClick={() => {
            setShowAmendments(false);
            setShowBills(true);
          }}
        >
          BILLS
        </button>
        <button
          className="flex"
          onClick={() => {
            setShowBills(false);
            setShowAmendments(true);
          }}
        >
          AMENDMENTS
        </button>
        <button
          className="flex"
          onClick={() => {
            setShowBills(false);
            setShowAmendments(false);
          }}
        >
          CLOSE
        </button>
      </div>
      {showBills ? <FetchBill /> : ""}
      {showAmendments ? <FetchAmendments /> : ""}
    </>
  );
}
