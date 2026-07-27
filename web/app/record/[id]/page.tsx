import Link from "next/link";
import { getJSON, type Claim, type Record_ } from "@/lib/api";

const LEVEL: Record<Claim["level"], { label: string; tone: string }> = {
  secure: { label: "secure", tone: "text-[var(--color-valid)]" },
  emerging: { label: "emerging", tone: "text-[var(--color-unknown)]" },
  not_evidenced: { label: "not evidenced", tone: "text-[var(--color-muted)]" },
};

export default async function RecordPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const record = await getJSON<Record_>(`/learners/${id}/record`);

  return (
    <main>
      <h1 className="text-xl font-semibold">{record.learner.handle}</h1>
      <p className="mb-10 text-xs text-[var(--color-muted)]">
        Capability record · generated {new Date(record.generated_at).toLocaleString()}
      </p>

      {record.claims.map((claim) => (
        <section
          key={claim.skill_id}
          className="border-t border-[var(--color-line)] py-5"
        >
          <div className="flex items-baseline justify-between gap-4">
            <h2 className="font-medium">{claim.skill_name}</h2>
            <span
              className={`text-xs font-bold uppercase tracking-widest ${LEVEL[claim.level].tone}`}
            >
              {LEVEL[claim.level].label}
            </span>
          </div>
          <p className="mt-1 text-sm text-[var(--color-muted)]">
            {claim.unaided_demonstrations} unaided demonstration
            {claim.unaided_demonstrations === 1 ? "" : "s"}
            {claim.assisted_demonstrations > 0 && (
              <em> · {claim.assisted_demonstrations} assisted, which do not count</em>
            )}
          </p>
          {claim.evidence.length > 0 && (
            <ul className="mt-2 space-y-1">
              {claim.evidence.map((item) => (
                <li key={item.attempt_id} className="text-sm">
                  <Link href={`/attempts/${item.attempt_id}`} className="underline">
                    {item.statement}
                  </Link>
                  <span className="text-[var(--color-muted)]">
                    {" "}
                    — {new Date(item.submitted_at).toLocaleDateString()}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}

      <footer className="mt-8 border-t border-[var(--color-line)] pt-5 text-xs text-[var(--color-muted)]">
        <p>{record.notes}</p>
        <p className="mt-2">
          Issued by {record.signature.issuer}, held by the learner. Signed with{" "}
          {record.signature.algorithm} ({record.signature.key_kind} key).
        </p>
        <p className="mt-4">
          <Link href="/" className="underline">
            Submit another attempt
          </Link>
        </p>
      </footer>
    </main>
  );
}
