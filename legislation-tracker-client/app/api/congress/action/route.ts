import { NextResponse } from "next/server";
import { resolveAllowedCongressActionUrl } from "./allowlisted-url";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const rawUrl = searchParams.get("url");

  if (!rawUrl) {
    return NextResponse.json({ error: "Missing url" }, { status: 400 });
  }

  const url = resolveAllowedCongressActionUrl(
    rawUrl,
    process.env.CONGRESS_API_KEY ?? process.env.NEXT_PUBLIC_CONGRESS_API_KEY,
  );
  if (!url) {
    return NextResponse.json({ error: "URL is not allowed" }, { status: 400 });
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
