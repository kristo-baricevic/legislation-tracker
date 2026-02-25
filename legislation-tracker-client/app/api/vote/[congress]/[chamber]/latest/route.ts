import { NextResponse } from "next/server";

export async function GET(
  request: Request,
  context: {
    params: Promise<{
      congress: string;
      chamber: string;
    }>;
  }
) {
  const { congress, chamber } = await context.params;

  const apiKey = process.env.NEXT_PUBLIC_CONGRESS_API_KEY;

  if (!apiKey) {
    return NextResponse.json(
      { error: "Missing CONGRESS API key" },
      { status: 500 }
    );
  }

  // Get latest vote by highest roll number
  const url = `https://api.congress.gov/v3/vote/${congress}/${chamber}?sort=rollNumber:desc&limit=1&api_key=${apiKey}`;

  try {
    const res = await fetch(url);

    if (!res.ok) {
      const text = await res.text();
      return NextResponse.json(
        { error: "Congress API error", details: text },
        { status: res.status }
      );
    }

    const data = await res.json();

    // The API returns an array under data.votes
    const latestVote = data?.votes?.[0];

    if (!latestVote) {
      return NextResponse.json(
        { error: "No votes found" },
        { status: 404 }
      );
    }

    return NextResponse.json({ vote: latestVote });
  } catch (err) {
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
