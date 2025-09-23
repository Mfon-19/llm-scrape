import { SubmitJobParams } from "@/app/types";
import { NextResponse } from "next/server";

export async function POST(request: Request) {
  try {
    const params: SubmitJobParams = await request.json();

    const response = await fetch(`${process.env.BACKEND_API_URL}/submit-job`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        prompt: params.prompt,
        ...(typeof params.maxPages === "number" && !Number.isNaN(params.maxPages)
          ? { max_pages: params.maxPages }
          : {}),
      }),
    });

    if (!response.ok) {
      return NextResponse.json(
        {
          error: `An error occured while submiting job: ${response.status} ${response.statusText}`,
        },
        { status: response.status }
      );
    }

    const result = await response.json();
    return NextResponse.json(result);
  } catch {
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
