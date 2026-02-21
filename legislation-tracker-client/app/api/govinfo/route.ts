import { NextResponse } from "next/server";

export async function GET() {
    const apiKey = process.env.GOVINFO_API_KEY;

    const url = `https://api.govinfo.gov/collections/BILLS/2025-01-01T00:00:00Z/2025-12-31T23:59:59Z?pageSize=100&offsetMark=*&api_key=${apiKey}`;

    const res = await fetch(url);

    const data = await res.json();

    return NextResponse.json(data);
}