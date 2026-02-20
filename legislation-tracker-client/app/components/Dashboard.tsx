"use client";

import React from "react";
import FetchBill from "./FetchBill";
import FetchAmendments from "./FetchAmendments";

export default function Dashboard() {
  const [showBills, setShowBills] = React.useState<boolean>(false);
  const [showAmendments, setShowAmendments] = React.useState<boolean>(false);
  return (
    <>
      <button
        onClick={() => {
          setShowAmendments(false);
          setShowBills(true);
        }}
      >
        BILLS
      </button>
      <button
        onClick={() => {
          setShowBills(false);
          setShowAmendments(true);
        }}
      >
        AMENDMENTS
      </button>
      {showBills ? <FetchBill /> : ""}
      {showAmendments ? <FetchAmendments /> : ""}
    </>
  );
}
