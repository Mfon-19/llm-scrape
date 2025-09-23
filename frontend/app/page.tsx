"use client";

import { useState } from "react";
import submitJob from "./actions";
import type { ScrapeJobResponse, ScrapedItem } from "./types";

type DisplayMode = "list" | "table" | "json" | "csv";

const detectDisplayMode = (input: string): DisplayMode => {
  const text = input.toLowerCase();
  if (text.includes("csv") || text.includes("spreadsheet")) {
    return "csv";
  }
  if (text.includes("table") || text.includes("tabular")) {
    return "table";
  }
  if (text.includes("json") || text.includes("array")) {
    return "json";
  }
  return "list";
};

const gatherFields = (items: ScrapedItem[]): string[] => {
  const fields = new Set<string>();
  items.forEach((item) => {
    Object.keys(item).forEach((key) => fields.add(key));
  });
  return Array.from(fields);
};

const buildCsv = (items: ScrapedItem[], fields: string[]): string => {
  const escapeCell = (value: string) => `"${value.replace(/"/g, '""').replace(/\r?\n|\r/g, " ")}"`;
  const headerRow = fields.join(",");
  const rows = items.map((item) =>
    fields.map((field) => escapeCell(item[field] ?? "")).join(",")
  );
  return [headerRow, ...rows].join("\n");
};

const hasStructuredData = (items: ScrapedItem[]): boolean =>
  items.some((item) => Object.keys(item).length > 0);

const formatMetadataValue = (value: unknown): string => {
  if (value === null || value === undefined) {
    return "—";
  }
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return "[unserializable]";
    }
  }
  return String(value);
};

const ItemsTable = ({ items, fields }: { items: ScrapedItem[]; fields: string[] }) => {
  if (!fields.length) {
    return <p className="text-sm text-gray-500">No structured fields were detected.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full border border-gray-200 text-sm">
        <thead className="bg-gray-50 text-gray-700">
          <tr>
            {fields.map((field) => (
              <th key={field} className="px-3 py-2 text-left font-semibold capitalize">
                {field}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {items.map((item, index) => (
            <tr key={`row-${index}`} className="bg-white">
              {fields.map((field) => (
                <td key={field} className="px-3 py-2 align-top text-gray-800">
                  {item[field] ?? "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const ItemsList = ({ items }: { items: ScrapedItem[] }) => (
  <div className="space-y-4">
    {items.map((item, index) => {
      const entries = Object.entries(item);
      return (
        <div
          key={`item-${index}`}
          className="rounded border border-gray-200 bg-white p-4 shadow-sm"
        >
          <p className="text-sm font-semibold text-gray-700">Result {index + 1}</p>
          {entries.length > 0 ? (
            <dl className="mt-2 space-y-2 text-sm">
              {entries.map(([key, value]) => (
                <div key={key}>
                  <dt className="font-medium capitalize text-gray-900">{key}</dt>
                  <dd className="break-words text-gray-700">{value || "—"}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="mt-2 text-sm text-gray-500">This result did not expose any labeled fields.</p>
          )}
        </div>
      );
    })}
  </div>
);

const ResultViewer = ({ result, mode }: { result: ScrapeJobResponse; mode: DisplayMode }) => {
  if (!result.items.length) {
    return <p className="text-sm text-gray-500">No items were extracted for this request.</p>;
  }

  const fields = gatherFields(result.items);

  if (mode === "json") {
    return (
      <pre className="mt-2 max-h-96 overflow-auto rounded bg-gray-900 p-4 text-sm text-gray-100">
        {JSON.stringify(result.items, null, 2)}
      </pre>
    );
  }

  if (mode === "csv") {
    if (!fields.length) {
      return <p className="text-sm text-gray-500">Structured fields are required to build CSV output.</p>;
    }
    return (
      <pre className="mt-2 max-h-96 overflow-auto rounded bg-gray-900 p-4 text-sm text-gray-100">
        {buildCsv(result.items, fields)}
      </pre>
    );
  }

  if (mode === "table") {
    return <ItemsTable items={result.items} fields={fields} />;
  }

  return <ItemsList items={result.items} />;
};

const JobDetails = ({ result }: { result: ScrapeJobResponse }) => {
  const { plan, metadata } = result;
  const coverageEntries = Object.entries(metadata.field_coverage ?? {});
  const sourceUrls = Array.isArray(metadata.source_urls) ? metadata.source_urls : [];
  const additionalMetadata = Object.entries(metadata).filter(
    ([key]) => !["item_count", "source_urls", "field_coverage"].includes(key)
  );

  return (
    <details className="mt-6 rounded border border-gray-200 bg-gray-50 p-4 text-sm text-gray-700">
      <summary className="cursor-pointer font-medium text-gray-800">View scraping details</summary>
      <div className="mt-3 space-y-4">
        <section>
          <h3 className="font-semibold text-gray-900">Plan</h3>
          <dl className="mt-2 space-y-2">
            <div>
              <dt className="font-medium text-gray-800">Seed URL</dt>
              <dd className="break-words text-gray-700">{plan.seed_url}</dd>
            </div>
            <div>
              <dt className="font-medium text-gray-800">Fields</dt>
              <dd className="text-gray-700">{plan.fields.join(", ") || "—"}</dd>
            </div>
            {plan.extra_urls.length > 0 && (
              <div>
                <dt className="font-medium text-gray-800">Extra URLs</dt>
                <dd className="space-y-1">
                  {plan.extra_urls.map((url, index) => (
                    <p key={`extra-${index}`} className="break-words">
                      {url}
                    </p>
                  ))}
                </dd>
              </div>
            )}
            {plan.requested_page_count ? (
              <div>
                <dt className="font-medium text-gray-800">Requested pages</dt>
                <dd className="text-gray-700">{plan.requested_page_count}</dd>
              </div>
            ) : null}
            {plan.notes.length > 0 && (
              <div>
                <dt className="font-medium text-gray-800">Notes</dt>
                <dd className="space-y-1">
                  {plan.notes.map((note, index) => (
                    <p key={`note-${index}`}>{note}</p>
                  ))}
                </dd>
              </div>
            )}
          </dl>
        </section>

        <section>
          <h3 className="font-semibold text-gray-900">Sources</h3>
          {sourceUrls.length > 0 ? (
            <ul className="mt-2 list-disc space-y-1 pl-5 text-gray-700">
              {sourceUrls.map((url, index) => (
                <li key={`source-${index}`} className="break-words">
                  {url}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-gray-500">No source URLs were captured.</p>
          )}
        </section>

        {coverageEntries.length > 0 && (
          <section>
            <h3 className="font-semibold text-gray-900">Field coverage</h3>
            <ul className="mt-2 space-y-1 text-gray-700">
              {coverageEntries.map(([field, coverage]) => (
                <li key={`coverage-${field}`}>
                  <span className="font-medium capitalize">{field}:</span> {Math.round(coverage * 100)}%
                </li>
              ))}
            </ul>
          </section>
        )}

        {additionalMetadata.length > 0 && (
          <section>
            <h3 className="font-semibold text-gray-900">Extra metadata</h3>
            <ul className="mt-2 space-y-1 text-gray-700">
              {additionalMetadata.map(([key, value]) => (
                <li key={`meta-${key}`}>
                  <span className="font-medium capitalize">{key.replace(/_/g, " ")}:</span> {formatMetadataValue(value)}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </details>
  );
};

export default function App() {
  const [prompt, setPrompt] = useState("");
  const [result, setResult] = useState<ScrapeJobResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [displayMode, setDisplayMode] = useState<DisplayMode>("list");

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedPrompt = prompt.trim();

    if (!trimmedPrompt) {
      setError("Please describe what you want to scrape.");
      setResult(null);
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const scrapeResult = await submitJob(trimmedPrompt);
      const preferredMode = detectDisplayMode(trimmedPrompt);
      const mode =
        (preferredMode === "table" || preferredMode === "csv") && !hasStructuredData(scrapeResult.items)
          ? "list"
          : preferredMode;

      setResult(scrapeResult);
      setDisplayMode(mode);
    } catch (submissionError) {
      setResult(null);
      setDisplayMode("list");
      setError(
        submissionError instanceof Error
          ? submissionError.message
          : "An unexpected error occurred."
      );
    } finally {
      setIsLoading(false);
    }
  };

  const hasItems = (result?.items.length ?? 0) > 0;
  const structured = result ? hasStructuredData(result.items) : false;

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-slate-950 px-6 py-16 text-white">
      <section className="w-full max-w-3xl rounded-2xl bg-slate-900 p-10 shadow-xl">
        <h1 className="text-3xl font-semibold text-white">Describe what you want to scrape</h1>
        <form onSubmit={handleSubmit} className="mt-6 space-y-4">
          <label className="block text-sm font-medium text-slate-200" htmlFor="prompt">
            Instructions
          </label>
          <textarea
            id="prompt"
            name="prompt"
            className="h-40 w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-sm text-white focus:border-teal-400 focus:outline-none"
            placeholder="Example: Find laptops under $1000 from example.com and return the results as a table"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
          />
          <button
            type="submit"
            disabled={isLoading}
            className="inline-flex items-center rounded-lg bg-teal-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-teal-400 disabled:cursor-not-allowed disabled:bg-slate-600"
          >
            {isLoading ? "Scraping…" : "Run scrape"}
          </button>
        </form>

        {error && (
          <p className="mt-4 rounded border border-red-400 bg-red-950/40 p-3 text-sm text-red-200">
            {error}
          </p>
        )}

        {result && !error && (
          <section className="mt-8 space-y-4">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-2xl font-semibold text-white">Results</h2>
                <p className="text-sm text-slate-300">
                  {result.metadata.item_count} item{result.metadata.item_count === 1 ? "" : "s"} collected
                </p>
              </div>
              {hasItems && (
                <label className="text-sm text-slate-300">
                  View as
                  <select
                    className="ml-2 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-white"
                    value={displayMode}
                    onChange={(event) => setDisplayMode(event.target.value as DisplayMode)}
                  >
                    <option value="list">Readable</option>
                    <option value="table" disabled={!structured}>
                      Table
                    </option>
                    <option value="json">JSON</option>
                    <option value="csv" disabled={!structured}>
                      CSV
                    </option>
                  </select>
                </label>
              )}
            </div>

            <ResultViewer result={result} mode={displayMode} />

            {result.errors.length > 0 && (
              <div className="rounded border border-red-400 bg-red-950/40 p-3 text-sm text-red-200">
                <p className="font-semibold">Errors</p>
                <ul className="mt-2 list-disc space-y-1 pl-5">
                  {result.errors.map((err, index) => (
                    <li key={`error-${index}`}>{err}</li>
                  ))}
                </ul>
              </div>
            )}

            {result.warnings.length > 0 && (
              <div className="rounded border border-amber-400 bg-amber-900/30 p-3 text-sm text-amber-100">
                <p className="font-semibold">Warnings</p>
                <ul className="mt-2 list-disc space-y-1 pl-5">
                  {result.warnings.map((warning, index) => (
                    <li key={`warning-${index}`}>{warning}</li>
                  ))}
                </ul>
              </div>
            )}

            <JobDetails result={result} />
          </section>
        )}
      </section>
    </main>
  );
}
