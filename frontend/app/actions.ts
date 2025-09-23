"use server";

import type { ScrapeJobResponse } from "./types";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

export default async function submitJob(prompt: string): Promise<ScrapeJobResponse> {
  const response = await fetch(`${process.env.NEXT_PUBLIC_BASE_URL}/api/scraper`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ prompt }),
  });

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error("The backend returned an unreadable response.");
  }

  if (!response.ok) {
    const errorMessage = isRecord(payload) && typeof payload.error === "string"
      ? payload.error
      : `Failed to submit job (${response.status})`;
    throw new Error(errorMessage);
  }

  if (!isRecord(payload) || !("plan" in payload) || !("items" in payload)) {
    throw new Error("Unexpected response from the backend.");
  }

  return payload as ScrapeJobResponse;
}
