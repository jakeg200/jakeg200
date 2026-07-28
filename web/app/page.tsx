"use client";

/**
 * The room. SPEC.md §2.
 *
 * A canvas, a voice, and no schedule. There is no progress bar, no score, no timer, and no next
 * button — every one of those is a sampling event wearing a friendly hat, and §3 rejects them.
 *
 * The transcript is deliberately quiet: the tutor's turns appear as small marginal notes rather
 * than as a chat thread, because a chat thread invites you to talk to it instead of working.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Canvas, { type Stroke } from "@/components/Canvas";

const API = process.env.ATRIUM_API ?? "http://localhost:8000";
const WS = process.env.ATRIUM_WS ?? "ws://localhost:8000";

type Turn = { move: string; text: string };

export default function Room() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [problem, setProblem] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [remote, setRemote] = useState<Stroke[]>([]);
  const [producer, setProducer] = useState(true);
  const socket = useRef<WebSocket | null>(null);
  const opened = useRef<number>(Date.now());

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API}/sessions`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ learner_id: "demo", problem_id: "le-03" }),
        });
        if (!res.ok) throw new Error(`${API} answered ${res.status}`);
        const body = await res.json();
        if (cancelled) return;
        setSessionId(body.session_id);
        setProblem(body.problem.statement);
      } catch (cause) {
        if (cancelled) return;
        // A bare "Failed to fetch" is either a dead backend or a blocked preflight, and the
        // browser deliberately won't tell you which. Say both rather than neither.
        setError(
          `Couldn't reach the API at ${API}. Is it running (uvicorn atrium.api.app:app --reload), ` +
            `and is this origin in ATRIUM_ALLOWED_ORIGINS? (${(cause as Error).message})`,
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!sessionId) return;
    const ws = new WebSocket(`${WS}/ws/${sessionId}`);
    socket.current = ws;

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "joined") setProducer(Boolean(message.producer));
      if (message.type === "stroke") setRemote((prev) => [...prev, message as Stroke]);
      if (message.type === "tutor") setTurns((prev) => [...prev, message as Turn]);
      // A recognition or realisation failure — e.g. no ANTHROPIC_API_KEY, or a leakage block
      // with nothing safe left to say. Surfaced rather than silently dropped (§10: silence is
      // supposed to mean "nothing to say," not "something broke").
      if (message.type === "error") setError(String(message.detail));
    };

    // The idle tick. The server needs a clock it can trust for stall detection (§6).
    const tick = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "tick", t_s: (Date.now() - opened.current) / 1000 }));
      }
    }, 1000);

    return () => {
      clearInterval(tick);
      ws.close();
    };
  }, [sessionId]);

  const send = useCallback((message: Record<string, unknown>) => {
    const ws = socket.current;
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ ...message, t_s: (Date.now() - opened.current) / 1000 }));
    }
  }, []);

  const onStroke = useCallback((stroke: Stroke) => send({ type: "stroke", ...stroke }), [send]);

  const onIdle = useCallback(
    async (png: Blob) => {
      const buffer = await png.arrayBuffer();
      const base64 = btoa(String.fromCharCode(...new Uint8Array(buffer)));
      send({ type: "snapshot", png: base64 });
    },
    [send],
  );

  return (
    <main className="flex h-dvh flex-col bg-paper text-ink">
      <header className="flex items-baseline justify-between border-b border-rule px-8 py-4">
        <h1 className="font-serif text-2xl tracking-tight">{problem || " "}</h1>
        {!producer && (
          <span className="text-xs uppercase tracking-widest text-ink/40">watching</span>
        )}
      </header>

      {error && (
        <p className="border-b border-rule bg-ink/5 px-8 py-3 text-sm text-ink/70">{error}</p>
      )}

      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1">
          <Canvas onStroke={onStroke} onIdle={onIdle} remote={remote} />
        </div>

        {/* Marginal notes, not a chat. Nothing here asks to be replied to. */}
        <aside className="w-72 shrink-0 overflow-y-auto border-l border-rule px-6 py-6">
          {turns.length === 0 ? (
            <p className="text-sm leading-relaxed text-ink/30">
              Work here. Nothing is being scored.
            </p>
          ) : (
            <ul className="space-y-6">
              {turns.map((turn, i) => (
                <li key={i} className="text-sm leading-relaxed text-ink/70">
                  {turn.text}
                </li>
              ))}
            </ul>
          )}
        </aside>
      </div>
    </main>
  );
}
