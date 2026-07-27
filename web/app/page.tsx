"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { API, type Task } from "@/lib/api";

const HANDLE_KEY = "warrant.handle";
const LEARNER_KEY = "warrant.learner";

export default function Submit() {
  const router = useRouter();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskId, setTaskId] = useState("lin-eq-007");
  const [text, setText] = useState("");
  const [handle, setHandle] = useState("");
  const [mode, setMode] = useState<"unassisted" | "assisted">("unassisted");
  const [attested, setAttested] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [learnerId, setLearnerId] = useState<string | null>(null);

  useEffect(() => {
    setHandle(localStorage.getItem(HANDLE_KEY) ?? "");
    setLearnerId(localStorage.getItem(LEARNER_KEY));
    fetch(`${API}/tasks`)
      .then((r) => r.json())
      .then(setTasks)
      .catch(() => setError("The API is not reachable. Is `make dev` running?"));
  }, []);

  const task = tasks.find((t) => t.id === taskId);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const learner = await fetch(`${API}/learners`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ handle: handle.trim() || "anonymous" }),
      }).then((r) => r.json());
      localStorage.setItem(HANDLE_KEY, handle.trim() || "anonymous");
      localStorage.setItem(LEARNER_KEY, learner.id);
      setLearnerId(learner.id);

      const response = await fetch(`${API}/attempts`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          learner_id: learner.id,
          task_id: taskId,
          raw_text: text,
          mode,
          attested: mode === "unassisted" ? attested : false,
        }),
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail ?? `submission failed (${response.status})`);
      }
      const attempt = await response.json();
      router.push(`/attempts/${attempt.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      setBusy(false);
    }
  }

  return (
    <main>
      <h1 className="mb-2 text-xl font-semibold">Show your working</h1>
      <p className="mb-8 max-w-prose text-sm text-[var(--color-muted)]">
        Write it however you normally would — ordinary words are fine, and so is unusual
        notation. Nothing is marked wrong unless it can be proved wrong.
      </p>

      <form onSubmit={submit} className="space-y-6">
        <div>
          <label className="mb-1 block text-sm font-medium">Task</label>
          <select
            value={taskId}
            onChange={(e) => setTaskId(e.target.value)}
            className="w-full rounded border border-[var(--color-line)] bg-transparent p-2 text-sm"
          >
            {tasks.map((t) => (
              <option key={t.id} value={t.id}>
                {t.statement}
              </option>
            ))}
          </select>
          {task && (
            <p className="mt-2 font-mono text-base">{task.statement}</p>
          )}
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium">Your working</label>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={8}
            required
            placeholder={"7x - 2 = 3x + 10\n4x - 2 = 10\n4x = 12\nx = 3"}
            className="w-full rounded border border-[var(--color-line)] bg-transparent p-3 font-mono text-sm"
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-sm font-medium">Your name or handle</label>
            <input
              value={handle}
              onChange={(e) => setHandle(e.target.value)}
              className="w-full rounded border border-[var(--color-line)] bg-transparent p-2 text-sm"
              placeholder="anonymous"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">How you worked</label>
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as "unassisted" | "assisted")}
              className="w-full rounded border border-[var(--color-line)] bg-transparent p-2 text-sm"
            >
              <option value="unassisted">On my own</option>
              <option value="assisted">With help</option>
            </select>
          </div>
        </div>

        {mode === "unassisted" && (
          <label className="flex items-start gap-2 rounded border border-[var(--color-line)] p-3 text-sm">
            <input
              type="checkbox"
              checked={attested}
              onChange={(e) => setAttested(e.target.checked)}
              className="mt-1"
            />
            <span>
              I worked this out myself, without a person, a model, or a solution to copy
              from.
              <span className="block text-xs text-[var(--color-muted)]">
                Only unassisted attempts can raise a level on your record. Attempts made
                with help are still recorded and still shown.
              </span>
            </span>
          </label>
        )}

        {error && <p className="text-sm text-[var(--color-broken)]">{error}</p>}

        <div className="flex items-center gap-4">
          <button
            type="submit"
            disabled={busy || (mode === "unassisted" && !attested)}
            className="rounded bg-[var(--color-ink)] px-4 py-2 text-sm text-[var(--color-paper)] disabled:opacity-40"
          >
            {busy ? "Reading your reasoning…" : "Submit"}
          </button>
          {learnerId && (
            <Link href={`/record/${learnerId}`} className="text-sm underline">
              See your record
            </Link>
          )}
        </div>
      </form>
    </main>
  );
}
