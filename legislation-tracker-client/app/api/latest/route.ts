import { NextResponse } from "next/server";

export async function GET() {
  const apiKey = process.env.NEXT_PUBLIC_CONGRESS_API_KEY;

  const url = `https://api.congress.gov/v3/bill?lawType=public&include=law&sort=updateDate+desc&limit=1&api_key=${apiKey}`;

  const res = await fetch(url);
  const data = await res.json();

  const bill = data.bills?.[0];

  if (!bill) {
    return NextResponse.json({ error: "No Public Law bill found" }, { status: 404 });
  }

  return NextResponse.json({
    congress: bill.congress,
    billType: bill.type.toLowerCase(),
    billNumber: bill.number,
    publicLaw: bill.laws?.[0]?.lawNumber,
  });
}