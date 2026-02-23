import { NextResponse } from "next/server";

export async function GET() {
    const apiKey = process.env.NEXT_PUBLIC_CONGRESS_API_KEY;

    const url = `https://api.congress.gov/v3/bill?sort=latestActionDate+desc&api_key=${apiKey}`;

    const res = await fetch(url);

    const data = await res.json();

    return NextResponse.json(data);
}