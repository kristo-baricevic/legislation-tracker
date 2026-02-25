import { NextResponse } from "next/server";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const congress = searchParams.get("congress") || "119";
  const billType = searchParams.get("type") || "hr";
  const apiKey = process.env.NEXT_PUBLIC_CONGRESS_API_KEY;

  const url = `https://api.congress.gov/v3/bill/${congress}/${billType}?sort=updateDate+desc&limit=20&api_key=${apiKey}`;

  const res = await fetch(url);

  if (!res.ok) {
    const text = await res.text();
    return NextResponse.json({ error: text }, { status: res.status });
  }

  const data = await res.json();
  return NextResponse.json(data);
}