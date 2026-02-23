import { NextResponse } from "next/server";

export async function GET(
  request: Request,
  {
    params,
  }: {
    params: {
      congress: string;
      billType: string;
      billNumber: string;
    };
  }
) {
  const apiKey = process.env.CONGRESS_API_KEY;

  const { congress, billType, billNumber } = params;

  const url = `https://api.congress.gov/v3/bill/${congress}/${billType}/${billNumber}?api_key=${apiKey}`;

  const res = await fetch(url);
  const data = await res.json();

  return NextResponse.json(data);
}