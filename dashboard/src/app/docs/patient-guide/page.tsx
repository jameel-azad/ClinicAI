import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Patient Guide – ClinicAI Docs",
  description: "How patients interact with ClinicAI over WhatsApp.",
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
  role: "patient" | "ai";
  children: React.ReactNode;
}) {
  const isPatient = role === "patient";
  return (
    <div className={`flex ${isPatient ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-xs rounded-xl px-4 py-2.5 text-sm leading-snug ${
          isPatient
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

export default function PatientGuidePage() {
  return (
    <article>
      <h1 className="text-2xl font-bold text-zinc-900 mb-2">Patient Guide</h1>
      <p className="text-zinc-500 text-sm mb-10">
        Patients interact with ClinicAI entirely through WhatsApp — no app
        download, no account creation.
      </p>

      <Section title="Starting a booking">
        <p>
          A patient simply messages the clinic&apos;s WhatsApp number. Any
          greeting or request to book triggers the booking flow.
        </p>
        <ChatDemo>
          <ChatBubble role="patient">Hi, I need an appointment</ChatBubble>
          <ChatBubble role="ai">
            Hello! I&apos;m the ClinicAI assistant. What are you coming in for
            today? Please briefly describe your symptoms or reason for visit.
          </ChatBubble>
        </ChatDemo>
      </Section>

      <Section title="Describing symptoms">
        <p>
          The patient describes their symptoms in plain language — English or
          Hinglish. The AI extracts the chief complaint and routes to the
          appropriate doctor or specialty.
        </p>
        <ChatDemo>
          <ChatBubble role="patient">
            Mujhe 2 din se bukhaar hai aur sar dard bhi ho raha hai
          </ChatBubble>
          <ChatBubble role="ai">
            Understood — fever and headache for 2 days. I&apos;ll check
            available slots with Dr. Ahsan. Which day works best for you?
          </ChatBubble>
        </ChatDemo>
        <p>
          Both English and Hinglish (Roman Urdu) are fully supported. Patients
          do not need to switch languages.
        </p>
      </Section>

      <Section title="Confirming appointment time">
        <p>
          The AI presents available slots and the patient picks one. Once
          confirmed, a booking request is sent to the doctor for approval.
        </p>
        <ChatDemo>
          <ChatBubble role="ai">
            Available slots tomorrow: 10:00 AM, 2:00 PM, 4:30 PM. Reply with
            the time you prefer.
          </ChatBubble>
          <ChatBubble role="patient">2 PM please</ChatBubble>
          <ChatBubble role="ai">
            Great! Your appointment is tentatively booked for tomorrow at 2:00
            PM with Dr. Ahsan. You&apos;ll receive a confirmation once the
            doctor approves.
          </ChatBubble>
        </ChatDemo>
      </Section>

      <Section title="Sending a lab report PDF">
        <p>
          Patients can send lab report PDFs directly in WhatsApp before or
          after a consultation. ClinicAI parses the report, extracts key values,
          and stores them against the patient record. The doctor sees a
          structured summary in their SOAP note.
        </p>
        <ChatDemo>
          <ChatBubble role="patient">
            [PDF: blood_test_results.pdf]
          </ChatBubble>
          <ChatBubble role="ai">
            Lab report received. I&apos;ve extracted your CBC and lipid panel
            results — Dr. Ahsan will review them before your appointment.
          </ChatBubble>
        </ChatDemo>
      </Section>

      <Section title="Post-consultation follow-up">
        <p>
          After a consultation the patient receives a follow-up message
          containing the doctor&apos;s advice summary, any prescribed
          medications, and a reminder to book a follow-up if recommended.
        </p>
        <ChatDemo>
          <ChatBubble role="ai">
            Your visit summary: Dr. Ahsan diagnosed viral fever. Prescribed
            Paracetamol 500mg twice daily for 3 days + ORS. Rest advised. Reply
            &quot;FOLLOWUP&quot; if symptoms persist after 3 days.
          </ChatBubble>
        </ChatDemo>
      </Section>

      <Section title="After-hours behaviour">
        <p>
          When the clinic is closed, patients are informed and added to the
          morning queue automatically. They receive a notification when the
          clinic opens.
        </p>
        <ChatDemo>
          <ChatBubble role="patient">Hi, need to book for today</ChatBubble>
          <ChatBubble role="ai">
            The clinic is currently closed (opens at 9:00 AM PKT). I&apos;ve
            added you to tomorrow morning&apos;s queue — you&apos;ll hear from
            us as soon as we open.
          </ChatBubble>
        </ChatDemo>
      </Section>

      <Section title="Supported languages">
        <ul className="list-disc list-inside space-y-1">
          <li>
            <strong>English</strong> — full support
          </li>
          <li>
            <strong>Hinglish</strong> (Roman Urdu mixed with English) — full
            support; no transliteration required
          </li>
        </ul>
        <p>
          Additional language support can be enabled by selecting a
          multilingual model such as Gemini 2.5 Flash in the AI Models settings.
        </p>
      </Section>
    </article>
  );
}
