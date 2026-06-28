import { NextResponse } from "next/server";

export async function GET(
  request: Request,
  context: {
    params: Promise<{
      id: string;
    }>;
  }
) {
  const apiKey = process.env.GOVINFO_API_KEY;
  const { id } = await context.params;

  const url = `https://api.govinfo.gov/packages/${id}/htm?api_key=${apiKey}`;

  const res = await fetch(url);
  const text = await res.text();

  return new NextResponse(text, {
    headers: { "Content-Type": "text/html" },
  });
}
