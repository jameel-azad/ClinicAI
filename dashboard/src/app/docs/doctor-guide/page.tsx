import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Doctor Guide – ClinicAI Docs",
  description: "How doctors interact with ClinicAI over WhatsApp.",
};

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-10">
      <h2 className="text-lg font-semibold text-zinc-900 mb-3">{title}</h2>
      <div className="text-sm text-zinc-600 leading-relaxed space-y-3">
        {children}
      </div>
    </section>
  );
}

function ChatBubble({
  role,
  children,
}: {
  role: "doctor" | "ai";
  children: React.ReactNode;
}) {
  const isDoctor = role === "doctor";
  return (
    <div className={`flex ${isDoctor ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-sm rounded-xl px-4 py-2.5 text-sm leading-snug ${
          isDoctor
            ? "bg-zinc-900 text-white rounded-br-sm"
            : "bg-zinc-100 text-zinc-800 rounded-bl-sm"
        }`}
      >
        {children}
      </div>
    </div>
  );
}

function ChatDemo({ children }: { children: React.ReactNode }) {
  return (
    <div className="border border-zinc-200 rounded-xl p-4 space-y-2.5 bg-white my-3">
      {children}
    </div>
  );
}

function ButtonRow({ labels }: { labels: string[] }) {
  return (
    <div className="flex gap-2 flex-wrap mt-1">
      {labels.map((label) => (
        <span
          key={label}
          className="inline-flex items-center rounded border border-zinc-300 bg-white px-3 py-1 text-xs font-medium text-zinc-700 shadow-sm"
        >
          {label}
        </span>
      ))}
    </div>
  );
}

function CodeBlock({ children }: { children: string }) {
  return (
    <pre className="rounded-lg bg-zinc-950 text-zinc-100 text-xs px-4 py-3 overflow-x-auto font-mono leading-relaxed">
      <code>{children}</code>
    </pre>
  );
}

export default function DoctorGuidePage() {
  return (
    <article>
      <h1 className="text-2xl font-bold text-zinc-900 mb-2">Doctor Guide</h1>
      <p className="text-zinc-500 text-sm mb-10">
        Doctors receive all notifications via WhatsApp. No separate app is
        required — a single tap approves, rejects, or reschedules.
      </p>

      <Section title="Appointment approval requests">
        <p>
          When a patient books a slot, you receive a WhatsApp message with the
          patient name, symptom summary, and requested time. Three quick-reply
          buttons let you act instantly.
        </p>
        <ChatDemo>
          <ChatBubble role="ai">
            New booking request
            {"\n"}
            Patient: Sara Khan{"\n"}
            Reason: Fever + headache (2 days){"\n"}
            Requested: Tomorrow, 2:00 PM
          </ChatBubble>
          <ButtonRow labels={["Approve", "Reject", "Suggest Time"]} />
        </ChatDemo>
        <ul className="list-disc list-inside space-y-1">
          <li>
            <strong>Approve</strong> — confirms the slot; patient is notified
            immediately.
          </li>
          <li>
            <strong>Reject</strong> — cancels the request; patient is asked to
            pick another time.
          </li>
          <li>
            <strong>Suggest Time</strong> — prompts you to type a preferred
            alternative time.
          </li>
        </ul>
      </Section>

      <Section title="Reviewing SOAP notes">
        <p>
          After each consultation the AI generates a SOAP note (Subjective,
          Objective, Assessment, Plan) and sends it to you for review.
        </p>
        <ChatDemo>
          <ChatBubble role="ai">
            SOAP note ready — Sara Khan{"\n"}S: Fever 38.5°C, headache 2
            days{"\n"}O: BP 120/80, no lymphadenopathy{"\n"}A: Viral fever
            {"\n"}P: Paracetamol 500mg BD × 3 days, rest, ORS
          </ChatBubble>
          <ButtonRow labels={["Approve", "Reject", "Regenerate"]} />
        </ChatDemo>
        <p>
          Approved notes are stored in the patient record and are available for
          FHIR export. Rejected notes are discarded and you can add a free-text
          note manually.
        </p>
      </Section>

      <Section title="REGEN command">
        <p>
          Use the <strong>REGEN</strong> command to regenerate a specific
          prescription or SOAP section with your feedback inline. The format is:
        </p>
        <CodeBlock>{`REGEN RX{id} Your feedback here`}</CodeBlock>
        <p>Example:</p>
        <CodeBlock>{`REGEN RX4821 Change antibiotic to Amoxicillin 500mg TDS, patient is allergic to penicillin`}</CodeBlock>
        <p>
          The AI will regenerate only the prescription section, apply your
          feedback, and resend the updated SOAP note for approval.
        </p>
      </Section>

      <Section title="Voice notes during consultation">
        <p>
          You can send WhatsApp voice notes at any point during or after a
          consultation. ClinicAI automatically transcribes the audio and
          appends it to the patient&apos;s encounter record. Transcriptions
          are used to update the SOAP note if sent while a consultation is
          active.
        </p>
        <ChatDemo>
          <ChatBubble role="doctor">[Voice note 0:23]</ChatBubble>
          <ChatBubble role="ai">
            Transcribed: &quot;Patient reports the pain is worse at night.
            Advising ibuprofen 400mg with food and a follow-up in one week if
            no improvement.&quot; Added to encounter notes.
          </ChatBubble>
        </ChatDemo>
      </Section>

      <Section title="Emergency alerts">
        <p>
          When an emergency is flagged — either by the triage AI or manually
          by clinic staff — a broadcast is sent to all registered doctors
          simultaneously. The message includes the patient name, contact
          number, and a brief triage summary.
        </p>
        <ChatDemo>
          <ChatBubble role="ai">
            EMERGENCY ALERT{"\n"}Patient: Bilal Hussain (+923001234567){"\n"}
            Triage: Chest pain, sweating, BP 90/60. Possible cardiac event.
            {"\n"}Please respond immediately.
          </ChatBubble>
        </ChatDemo>
      </Section>

      <Section title="Weekly practice insights">
        <p>
          Every Monday at <strong>8:00 AM IST</strong> you receive a weekly
          digest covering:
        </p>
        <ul className="list-disc list-inside space-y-1">
          <li>Total appointments vs. previous week</li>
          <li>Top 3 presenting complaints</li>
          <li>No-show rate</li>
          <li>Average consultation duration</li>
          <li>Pending SOAP note approvals</li>
        </ul>
        <p>
          The digest is sent to all doctors on the clinic. You can disable it
          per doctor under <strong>Settings → Notifications</strong>.
        </p>
      </Section>
    </article>
  );
}
