"use client";

import { useState } from "react";
import submitJob from "./actions";

export default function App() {
  const [prompt, setPrompt] = useState("");
  const [response, setResponse] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const result = await submitJob(prompt);
      setResponse(result.message);
    } catch {
      setResponse("An unexpected error occured");
    }
  };

  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-24">
      <h1 className="text-4xl font-bold mb-8">What do you want to scrape?</h1>
      <form onSubmit={handleSubmit} className="w-full max-w-md">
        <div className="flex flex-col items-center py-2">
          <textarea
            className="appearance-none bg-transparent border-2 border-teal-500 rounded w-full text-gray-700 mr-3 py-1 px-2 leading-tight focus:outline-none h-40"
            placeholder="Enter your prompt"
            aria-label="Prompt for backend"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
          <button
            className="flex-shrink-0 bg-teal-500 hover:bg-teal-700 border-teal-500 hover:border-teal-700 text-sm border-4 text-white py-1 px-2 rounded mt-4"
            type="submit">
            Scrape
          </button>
        </div>
      </form>
      {response && (
        <div className="mt-8 p-4 border-2 border-gray-300 rounded-md w-full max-w-md">
          <h2 className="text-2xl font-bold mb-4">Response</h2>
          <p>{response}</p>
        </div>
      )}
    </main>
  );
}
