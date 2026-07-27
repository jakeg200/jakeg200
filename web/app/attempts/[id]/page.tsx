import Link from "next/link";
import { getJSON, type Attempt, type Step } from "@/lib/api";

const TONE: Record<Step["status"], string> = {
  valid: "text-[var(--color-valid)]",
  invalid: "text-[var(--color-broken)]",
  unverifiable: "text-[var(--color-unknown)]",
};

const GLYPH: Record<Step["status"], string> = {
  valid: "✓",
  invalid: "✗",
  unverifiable: "?",
};

const NOTE: Record<Step["status"], string> = {
  valid: "follows",
  invalid: "does not follow",
  unverifiable: "could not be checked",
};

export default async function AttemptPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const attempt = await getJSON<Attempt>(`/attempts/${id}`);
  const brk = attempt.diagnosis.first_break_index;

  return (
    <main>
      <p className="mb-1 text-xs uppercase tracking-widest text-[var(--color-muted)]">
        {attempt.mode === "unassisted" ? "unassisted (self-declared)" : attempt.mode}
      </p>
      <h1 className="mb-8 font-mono text-lg">{attempt.statement}</h1>

      <ol className="mb-8 space-y-1">
        {attempt.steps.map((step) => {
          const broken = brk === step.index;
          return (
            <li
              key={step.index}
              className={`rounded border p-3 ${
                broken
                  ? "border-[var(--color-broken)]"
                  : "border-transparent"
              }`}
            >
              <div className="flex items-start gap-3">
                <span className={`mt-0.5 w-4 shrink-0 ${TONE[step.status]}`}>
                  {GLYPH[step.status]}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="font-mono text-sm break-words">{step.raw_text}</p>
                  <p className="mt-1 text-xs text-[var(--color-muted)]">
                    {NOTE[step.status]}
                    {step.evidence ? ` — ${step.evidence}` : ""}
                    {step.status !== "unverifiable" && ` · tier ${step.tier}`}
                  </p>
                  {broken && (
                    <p className="mt-1 text-xs font-medium text-[var(--color-broken)]">
                      the reasoning goes wrong here
                      {step.status === "valid" &&
                        " — this line is true on its own, but it is what the later step inherits"}
                    </p>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ol>

      <section className="border-t border-[var(--color-line)] pt-6">
        <p className="mb-4 text-sm">{attempt.diagnosis.summary}</p>
        {attempt.probe && (
          <blockquote className="border-l-2 border-[var(--color-ink)] pl-4">
            <p className="text-base">{attempt.probe}</p>
            {attempt.diagnosis.misconception_name && (
              <p className="mt-2 text-xs text-[var(--color-muted)]">
                {attempt.diagnosis.misconception_name}
              </p>
            )}
          </blockquote>
        )}
        {!attempt.diagnosis.derivation_present && brk === null && (
          <p className="mt-4 text-xs text-[var(--color-muted)]">
            Nothing here is wrong — but nothing here derives anything either, so this
            attempt does not move your record.
          </p>
        )}
      </section>

      <nav className="mt-10 flex gap-4 text-sm">
        <Link href="/" className="underline">
          Another attempt
        </Link>
        <Link href={`/record/${attempt.learner_id}`} className="underline">
          Your record
        </Link>
      </nav>
    </main>
  );
}
