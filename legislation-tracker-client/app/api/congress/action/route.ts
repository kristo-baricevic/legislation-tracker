import { NextResponse } from "next/server";

export async function GET(request: Request) {
    const { searchParams } = new URL(request.url);
    const url = searchParams.get("url");

    if (!url) {
    return NextResponse.json({ error: "Missing url" }, { status: 400 });
    }

    const apiKey = process.env.NEXT_PUBLIC_CONGRESS_API_KEY;

    const finalUrl = `${url}&api_key=${apiKey}`;

    const res = await fetch(finalUrl, { cache: "no-store" });

    const contentType = res.headers.get("content-type");

    if (contentType?.includes("application/json")) {
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
    }

    const text = await res.text();
    return new Response(text, {
        status: res.status,
        headers: { "content-type": contentType || "text/plain" },
    });

}