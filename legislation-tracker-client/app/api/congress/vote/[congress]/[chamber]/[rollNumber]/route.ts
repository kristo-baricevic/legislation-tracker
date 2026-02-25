import { NextResponse } from "next/server";

export async function GET(
  request: Request,
  context: {
    params: Promise<{
      congress: string;
      chamber: string;
      rollNumber: string;
    }>;
  }
) {
  const { congress, chamber, rollNumber } = await context.params;

  const apiKey = process.env.NEXT_PUBLIC_CONGRESS_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ error: "Missing CONGRESS API key" }, { status: 500 });
  }

  const url = `https://api.congress.gov/v3/${chamber}/votes/${congress}/${rollNumber}?api_key=${apiKey}`;  const res = await fetch(url, { cache: "no-store" });
  const data = await res.json();

  return NextResponse.json(data, { status: res.status });
}