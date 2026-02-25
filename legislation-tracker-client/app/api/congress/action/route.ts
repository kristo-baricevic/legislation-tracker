import { NextResponse } from "next/server";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const rawUrl = searchParams.get("url");

  if (!rawUrl) {
    return NextResponse.json({ error: "Missing url" }, { status: 400 });
  }

  const apiKey = process.env.NEXT_PUBLIC_CONGRESS_API_KEY;

  // Append api_key if calling api.congress.gov
  let url = rawUrl;

  if (url.includes("api.congress.gov") && !url.includes("api_key=")) {
    const separator = url.includes("?") ? "&" : "?";
    url = `${url}${separator}api_key=${apiKey}`;
  }

  const res = await fetch(url);

  const contentType = res.headers.get("content-type") || "";

  if (contentType.includes("application/json")) {
    const json = await res.json();
    return NextResponse.json(json, { status: res.status });
  }

  const text = await res.text();
  return new Response(text, {
    status: res.status,
    headers: { "content-type": contentType },
  });
}