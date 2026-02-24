import { NextResponse } from "next/server";

export async function GET(
  request: Request,
  context: {
    params: Promise<{
      congress: string;
      billType: string;
      billNumber: string;
    }>;
  }
) {
  const { congress, billType, billNumber } = await context.params;

  const apiKey = process.env.NEXT_PUBLIC_CONGRESS_API_KEY;

  const url = `https://api.congress.gov/v3/bill/${congress}/${billType}/${billNumber}/votes?api_key=${apiKey}`;

  const res = await fetch(url);
  const data = await res.json();

  return NextResponse.json(data);
}