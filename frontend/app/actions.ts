"use server";

export default async function submitJob(prompt: string) {
  try {
    const response = await fetch(
      `${
        process.env.NEXT_PUBLIC_BASE_URL
      }/api/scraper`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ prompt }),
      }
    );

    if (!response.ok) {
      throw new Error("Failed to submit job");
    }

    const result = await response.json();
    return result;
  } catch {
    throw new Error("Failed to submit job");
  }
}
